import os
import pandas as pd
import mysql.connector
from sqlalchemy import create_engine, URL, text
from dotenv import load_dotenv
from google import genai
import numpy as np
from mcp.server import MCPServer
from sklearn.metrics.pairwise import cosine_similarity

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

client = genai.Client()

def get_embedding(text: str, model="gemini-embedding-001") -> list[float]:
    text = text.replace("\n", " ").strip()[:8000]  # max token safety
    response = client.models.embed_content(model=model, contents=text)
    return response.embeddings[0].values

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
    with engine.connect() as connection:
        result = connection.execution_options(stream_results=True).execute(text("SELECT source_id, embedding from row_embeddings").columns(embedding=JSON()))

        embeddings = [
            (str(row.source_id), row.embedding)
            for row in result
        ]

    return find_similar_listings(query, embeddings, top_k)


# ------------------------------------------------------------------------------------------------------------------------------------------------------------

def calculate_similarity_score(
    target: dict,
    candidate: dict,
    target_emb: list[float],
    candidate_emb: list[float]
) -> float:
    score = 0.0
    # Structured similarity (60% of total score)
    price_diff = abs(target["L_SystemPrice"] - candidate["L_SystemPrice"])
    if price_diff < 50_000:   score += 20
    elif price_diff < 150_000: score += 12
    elif price_diff < 300_000: score += 5
    if target["L_Keyword2"] == candidate["L_Keyword2"]:       score += 15
    if target["L_City"]     == candidate["L_City"]:           score += 15
    sqft_diff = abs(target["LM_Int2_3"] - candidate["LM_Int2_3"])
    if sqft_diff < 300:  score += 10
    elif sqft_diff < 700: score += 5
    # Semantic similarity (40% of total score)
    from sklearn.metrics.pairwise import cosine_similarity
    import numpy as np
    sem_sim = cosine_similarity(
        np.array(target_emb).reshape(1,-1),
        np.array(candidate_emb).reshape(1,-1)
    )[0][0]
    score += sem_sim * 40
    return round(score, 2)

# Check if recommended price is supported by recent comps
def validate_with_comps(city: str, sqft: int, price: int) -> dict:
    sql = """
        SELECT
          AVG(ClosePrice / NULLIF(LivingArea,0)) AS avg_ppsf,
          COUNT(*) AS comp_count
        FROM california_sold
        WHERE City = %s AND PropertyType = 'Residential'
          AND LivingArea BETWEEN %s AND %s
          AND CloseDate >= DATE_SUB(CURDATE(), INTERVAL 6 MONTH)
    """
    result = query(sql, [city, sqft * 0.8, sqft * 1.2])
    avg_ppsf = result[0]["avg_ppsf"] or 0
    comp_price = avg_ppsf * sqft
    return {
        "comp_price":  round(comp_price),
        "list_price":  price,
        "comp_count":  result[0]["comp_count"],
        "delta_pct":   round((price - comp_price) / comp_price * 100, 1)
    }

# --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

# 1. Chunk documents
def chunk_text(text: str, chunk_size=600, overlap=100) -> list[str]:
    chunks, start = [], 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        chunks.append(text[start:end])
        start += chunk_size - overlap
    return chunks

# 2. Index chunks
def index_documents(docs: list[dict]) -> list[dict]:
    indexed = []
    for doc in docs:
        for chunk in chunk_text(doc["content"]):
            indexed.append({
                "source": doc["title"],
                "chunk":  chunk,
                "embedding": get_embedding(chunk)
            })
    return indexed

# 3. Retrieve relevant chunks for a query
def retrieve(query: str, index: list[dict], top_k=4) -> list[dict]:
    q_emb = np.array(get_embedding(query)).reshape(1,-1)
    scored = [
        (doc, cosine_similarity(q_emb, np.array(doc["embedding"]).reshape(1,1))[0][0])
        for doc in index
    ]
    scored.sort(key=lambda x: x[1], reverse=True)
    return [doc for doc, _ in scored[:top_k]]

# 4. Generate grounded answer
def rag_answer(query: str, index: list[dict]) -> str:
    chunks = retrieve(query, index)
    context = "\n\n".join(c["chunk"] for c in chunks)
    prompt = f"Answer using only the context below:\n\n{context}\n\nQuestion: {query}"
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}]
    )
    return resp.choices[0].message.content

#start the server
if __name__ == "__main__":
    mcp.run(transport="stdio")