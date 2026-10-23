---
name: database-query
description: Query the local database using processed user filters to retrieve active housing listings and sold listing.
---

# Database Query

Use the `session_memory` MCP tool to keep track of the users inquiry session. If the user is inquiring about housing information and the tool returns missing values ask the user for clarification on the missing information. Once all information is provided, take the returned result from the tool and create a sentence using all the information provided. Use the `get_housing_information` MCP tool and use the sentence created before to query the database and return results

## Workflow

1. Read the user's database-related request.
2. If it is missing information ask follow up questions
3. Formulate a request using all the information passed by the user
4. Call the `query_database` MCP tool.
3. Pass the complete request in the `request` field.
4. The TypeScript MCP server will:
   - process the request into filters,
   - build the SQL query,
   - query the database,
   - return the results.
5. Present the results clearly to the user.

## Rules

- Do not write SQL directly.
- Do not ask the user for database credentials.
- Do not expose `.env` values.
- Do not invent filters or database results.
- If required information is missing, ask the user for clarification.
- If no records are found, clearly state that no matching records were found.
- If the database tool returns an error, explain that the database request failed.

## Tool input

Call the tool with an object like:

{
  "request": "Show me 3-bedroom condos in Irvine under $1.5M with a pool."
}