import os
import pandas as pd
import mysql.connector
from sqlalchemy import create_engine, URL
from dotenv import load_dotenv
from openai import OpenAI
import numpy as np
from mcp.server import MCPServer

mcp = MCPServer("housing_analysis_tool")

# Python Trend Analysis


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

# ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------

client = OpenAI()

# connection = mysql.connector.connect(
#     user = os.environ["MYSQL_USER"],
#     password = os.environ["MYSQL_PASSWORD"],
#     host = os.environ["MYSQL_HOST"],
#     port = os.environ["MYSQL_PORT"],
#     database = os.environ["MYSQL_DATABASE"]
# )

# # creates a way to pass calls to the sql database 
# cursor = connection.cursor(dictionary=True)

# # retrieves all rows and stores each row as a map with the column being the key
# cursor.execute("SELECT * FROM rets_property")

def get_embedding(text: str, model="text-embedding-3-small") -> list[float]:
    text = text.replace("\n", " ").strip()[:8000]  # max token safety
    response = client.embeddings.create(model=model, input=text)
    return response.data[0].embedding
# Build embedding for a listing (combine key fields)

def build_listing_embedding(row: dict) -> list[float]:
    text = f"""
        {row["L_Type_"]} in {row["L_City"]}, CA.
        {row["L_Keyword2"]} beds, {row["LM_Dec_3"]} baths.
        {row["LM_Int2_3"]} sq ft. Built {row["YearBuilt"]}.
        Price: ${row["L_SystemPrice"]:,}.
        {row.get("L_Remarks", "")}
    """.strip()
    return get_embedding(text)

#builds the listing embeddings for find_similar_listings
def build_all_embeddings():
    embeddings = []
    for row in cursor:
        embeddings.append((row["L_ListingID"], build_listing_embedding(row)))
    return embeddings

from sklearn.metrics.pairwise import cosine_similarity

def find_similar_listings(
    query: str,
    listing_embeddings: list[tuple[str, list[float]]],
    top_k: int = 5
) -> list[str]:
    """Return top_k listing IDs most similar to the query."""
    query_vec = np.array(get_embedding(query)).reshape(1, -1)
    scores = []
    for listing_id, emb in listing_embeddings:
        sim = cosine_similarity(query_vec, np.array(emb).reshape(1, -1))[0][0]
        scores.append((listing_id, float(sim)))
    scores.sort(key=lambda x: x[1], reverse=True)
    return [lid for lid, _ in scores[:top_k]]

@mcp.tool()
def vector_embedding_search(query, top_k):
    embeddings = build_all_embeddings()
    return find_similar_listings(query, embeddings, top_k)



#start the server
if __name__ == "__main__":
    mcp.run(transport="stdio")