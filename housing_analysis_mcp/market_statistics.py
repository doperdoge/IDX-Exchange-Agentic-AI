from mcp.server import MCPServer

mcp = MCPServer("housing_analysis_tool")

# Python Trend Analysis
import os
import pandas as pd
import mysql.connector
from sqlalchemy import create_engine, URL
from dotenv import load_dotenv

load_dotenv()

#create the sql link
engine = create_engine(
    URL.create(
        "mysql+mysqlconnector",
        username = os.environ["MYSQL_USER"],
        password = os.environ["MYSQL_PASSWORD"],
        host = os.environ["MYSQL_HOST"],
        port = os.environ["MYSQL_PORT"],
        database = os.environ["MYSQL_DATABASE"]
    )
)

# Monthly price trends for a city
@mcp.tool()
def get_price_trend(city: str, months: int = 24):
    query = """
        SELECT
            DATE_FORMAT(CloseDate, "%Y-%m") AS month,
            COUNT(*)                        AS sales,
            ROUND(AVG(ClosePrice), 0)       AS avg_price,
            ROUND(AVG(DaysOnMarket), 1)     AS avg_dom
        FROM california_sold
        WHERE City = %s
          AND PropertyType = "Residential"
          AND CloseDate >= DATE_SUB(CURDATE(), INTERVAL %s MONTH)
        GROUP BY DATE_FORMAT(CloseDate, "%Y-%m")
        ORDER BY month
    """
    df = pd.read_sql(query, engine, params=[city, months])
    df["price_change_pct"] = df["avg_price"].pct_change() * 100
    return df


#start the server

if __name__ == "__main__":
    mcp.run(transport="stdio")