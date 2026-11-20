from sqlalchemy import create_engine, URL, text, Table, Column, MetaData, String, JSON, DateTime, func 
from sqlalchemy.dialects.mysql import insert
from dotenv import load_dotenv
from google import genai
import os
import pandas as pd

load_dotenv()

client = genai.Client()
metadata = MetaData()

# embedding table to be uploaded to mysql
embedding_table = Table(
    "row_embeddings",
    metadata,
    Column("source_id", String(255), primary_key=True),
    Column("embedding", JSON, nullable=False),
    Column(
        "updated_at",
        DateTime,
        nullable=False,
        server_default=func.now(),
    ),
)

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

def get_embedding(text: str, model="gemini-embedding-001") -> list[float]:
    text = text.replace("\n", " ").strip()[:8000]  # max token safety
    response = client.models.embed_content(model=model, contents=text)
    return response.embeddings[0].values
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

def build_all_embeddings():
    print('Creating embeddings please wait...')
    embeddings = []
    with engine.connect() as connection:
        result = connection.execution_options(
            stream_results=True
        ).execute(text("SELECT * from rets_property LIMIT 5000"))
        idx = 1
        for row in result.mappings():
            print(f"Embedding in progress {idx}")
            embeddings.append((row["L_ListingID"], build_listing_embedding(row)))
            idx += 1
    print('Embeddings Created!')
    return embeddings

def save_embeddings(engine, embeddings):
    print('Starting Save')
    embedding_table.create(engine, checkfirst=True)

    for start in range(0, len(embeddings), 100):
        batch = [
            {
                "source_id": str(row_id),
                "embedding": [float(value) for value in embedding],
            }
            for row_id, embedding in embeddings[start:start + 100]
        ]

        statement = insert(embedding_table)

        statement = statement.on_duplicate_key_update(
            embedding=statement.inserted.embedding,
            updated_at=func.now(),
        )

        with engine.begin() as connection:
            connection.execute(statement, batch)

    print("Embeddings saved!")

def main(): 
    emb = build_all_embeddings()
    save_embeddings(engine, emb)

if __name__ == "__main__":
    main()

#Completed