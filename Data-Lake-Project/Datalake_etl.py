import configparser
from datetime import datetime
import os
from pyspark.sql import SparkSession
from pyspark.sql.functions import udf, col
from pyspark.sql.functions import year, month, dayofmonth, hour, weekofyear, date_format
from pyspark.sql.types import StructType as R, StructField as Fld, DoubleType as Dbl, StringType as Str, IntegerType as Int, DateType as Date, TimestampType


config = configparser.ConfigParser()
config.read('dl.cfg')

os.environ['AWS_ACCESS_KEY_ID']=config['KEYS']['AWS_ACCESS_KEY_ID']
os.environ['AWS_SECRET_ACCESS_KEY']=config['KEYS']['AWS_SECRET_ACCESS_KEY']


def create_spark_session():
    """
    Create a Spark Session
    """
    spark = SparkSession \
        .builder \
        .config("spark.jars.packages", "org.apache.hadoop:hadoop-aws:2.7.0") \
        .getOrCreate()
    return spark


def process_song_data(spark, input_data, output_data):
    """
    Description: This function loads song_data from S3, processes it by extracting the songs and artist tables, 
    and then load song table and artist table back to data lake on S3.
        
    Parameters:
        spark       : Spark Session
        input_data  : path of song_data json files
        output_data : songs_table and artists_table in parquet files
    """
    
    
    # get filepath to song data file
    song_data = input_data + 'song_data/*/*/*/*.json'
    
    #create song schema
    song_schema = R([
        Fld("num_songs",Int()),
        Fld("artist_id",Str()),
        Fld("artist_latitude",Dbl()),
        Fld("artist_longitude",Dbl()),
        Fld("artist_location",Str()),
        Fld("artist_name",Str()),
        Fld("song_id",Str()),
        Fld("title",Str()),
        Fld("duration",Dbl()),
        Fld("year",Int()),
    ]) 
    
    # read song data file
    df = spark.read.json(song_data, schema = song_schema)

    # extract columns to create songs table
    columns = ["song_id", "title", "artist_id", "year", "duration"]
    songs_table = df.select(columns)
    
    # write songs table to parquet files partitioned by year and artist
    songs_table.write.partitionBy("year", "artist_id").parquet(output_data + 'songs/')

    # extract columns to create artists table
    art_cols = ["artist_id", "artist_name as name", "artist_location as location", "artist_lattitude as lattitude", "artist_longitude as longitude"]
    artists_table =  df.selectExpr(art_cols).dropDuplicates()
    
    # write artists table to parquet files
    artists_table.write.parquet(output_data + "artists/")


def process_log_data(spark, input_data, output_data):
    """
        This function loads log_data from S3, extract user and time tables from log_data, create fact table song_play and finally push back to S3.
        
        Parameters:
            spark       : Spark Session
            input_data  : log_data, processed artist and song table
            output_data : dimensional tables and fact table in parquet format load to S3 bucket  
    """
    
    
    # get filepath to log data file
    log_data = input_data + 'log_data/*/*/*.json'

    # read log data file
    df = spark.read.json(log_data)
    
    # filter by actions for song plays
    df = df.filter(df.page == 'NextPage')

    # extract columns for users table    
    user_cols = ["userdId AS user_id", "firstName AS first_name", "lastName AS last_name", "gender", "level"]
    user_table = df.selectExpr(user_cols).dropDuplicates()
    
    # write users table to parquet files
    user_table.write.parquet(output_data + 'users/')

    # create timestamp column from original timestamp column
    get_datetime = udf(lambda x: datetime.utcfromtimestamp(int(x)/1000), TimestampType())
    df = df.withColumn("start_time", get_datetime("ts"))
    
    # extract columns to create time table
    time_table = df.select("start_time").dropDuplicates()\
                   .withColumn("hour", hour("start_time"))\
                   .withColumn("day", dayofmonth("start_time"))\
                   .withColumn("week", weekofyear("start_time"))\
                   .withColumn("month", month("start_time"))\
                   .withColumn("year", year("start_time"))\
                   .withColumn("weekday", dayofweek("start_time"))\
                   .select("")
    
    # write time table to parquet files partitioned by year and month
    time_table.write.parquet(os.path.join(output_data, "time/"), mode='overwrite', partitionBy=["year","month"])

    # read in song data to use for songplays table
    df_songs = spark.read.parquet(output_data + 'songs/*/*/*')

    # extract columns from joined song and log datasets to create songplays table 
    df_artists = spark.read.parquet(output_data + 'artists/*')
    
    log_songs = df.join(df_songs, df.song == df_songs.title).drop(df_songs.year)
    log_song_artist = log_songs.join(df_artists, log_songs.artist == df_artists.name)
    songplays_table = log_song_artist.join(time_table, log_song_artist.start_time == time_table.start_time)\
                                     .select(monotonically_increasing_id().alias("songplay_id"),
                                             col("start_time"),
                                             col("userId").alias("user_id"),
                                             "level",
                                             "song_id",
                                             "artist_id",
                                             col("sessionId").alias("session_id"),
                                             "location",
                                             col("userAgent").alias("user_agent"),
                                             "year",
                                             "month")

    # write songplays table to parquet files partitioned by year and month
    songplays_table.write.partitionBy("year","month").parquet(output_data + "songplays/")


def main():
    """
        Extract songs and log data from S3, Transform the data into the format of dimensional and fact tables, and Load the processed data to S3 in Parquet format
    """
    spark = create_spark_session()
    input_data = "s3a://udacity-dend/"
    output_data = "s3a://datalake-project-jin/output/"
    
    process_song_data(spark, input_data, output_data)    
    process_log_data(spark, input_data, output_data)


if __name__ == "__main__":
    main()
