import "dotenv/config";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import mysql from "mysql2/promise";
import { z } from "zod";

const pool = mysql.createPool({
    host:     process.env.MYSQL_HOST,
    port:     Number(process.env.MYSQL_PORT),
    user:     process.env.MYSQL_USER,
    password: process.env.MYSQL_PASSWORD,
    database: process.env.MYSQL_DATABASE,
    waitForConnections: true,
    connectionLimit: 10,
    queueLimit: 0,
});

const server = new McpServer({
    name: "housing_db",
    version: "1.0.0"
})

server.registerTool(
    "get_housing_information",
    {
        description: "Find housing information for a query",
        //Verifies there is an object to look at 
        inputSchema: z.object({
            request: z.string().min(1),
        }),
    },
    async ({request}) => {
        const filters = await parsePropertyQuery(request);
        const active_listing = await searchActiveListings(filters);
        
        if (filters.city){
            const sold_comp = await getSoldComps(filters.city as string);

            return {
                content: [
                    {
                        type: "text",
                        text: JSON.stringify({active_listing, sold_comp}, null, 2),
                    },
                ],
            };
        }
        else{
            return {
                content: [
                    {
                        type: "text",
                        text: JSON.stringify({active_listing}),
                    },
                ],
            };
        }
    }
)

export async function query<T>(sql: string, params: any[] = []): Promise<T[]> {
    const [rows] = await pool.execute(sql, params);
    return rows as T[];
}

export async function getCurrentTime() {
    return { currentTime: new Date().toISOString() };
}

export async function handleMessage(message: string) {
    if (message.toLowerCase().includes("time")) {
        return await getCurrentTime();
    }
    return { response: "I could not understand the request." };
}

type PropertyFilters = {
    city:     string | null;
    maxPrice: number | null;
    beds:     number | null;
    baths:    number | null;
    sqft:     number | null;
    type:     string | null;
    pool:     string | null;
    hasView:  string | null;
};

export async function parsePropertyQuery(query: string): Promise<PropertyFilters> {
    const cityMatch   = query.match(/in ([A-Za-z\s]+?)(?:\s+under|\s+with|\s+at|$)/i);
    const priceMatch  = query.match(/under \$?([\d,.]+)(k|m)?/i);
    const bedsMatch   = query.match(/(\d+)[\s-]*(bed|beds|bedroom|bedrooms)/i);
    const bathsMatch  = query.match(/(\d+(?:\.5)?)[\s-]*(bath|baths|bathroom)/i);
    const sqftMatch   = query.match(/(\d+)[\s,]*(sqft|sq ft|square feet)/i);
    const poolMatch   = /pool/i.test(query);
    const viewMatch   = /view/i.test(query);
    const typeMap: Record<string,string> = {
        condo: "Condominium", townhome: "Townhouse",
        "single family": "SingleFamilyResidence", land: "UnimprovedLand"
    };
    const typeKey = Object.keys(typeMap).find(k => query.toLowerCase().includes(k));
    let maxPrice = null;
    if (priceMatch) {
        maxPrice = Number(priceMatch[1].replace(/,/g, ""));
        if (priceMatch[2]?.toLowerCase() === "k") maxPrice *= 1000;
        if (priceMatch[2]?.toLowerCase() === "m") maxPrice *= 1_000_000;
    }
    return {
        city:     cityMatch?.[1]?.trim() || null,
        maxPrice,
        beds:     bedsMatch  ? Number(bedsMatch[1])  : null,
        baths:    bathsMatch ? Number(bathsMatch[1]) : null,
        sqft:     sqftMatch  ? Number(sqftMatch[1])  : null,
        type:     typeKey ? typeMap[typeKey] : null,
        pool:     poolMatch ? "True" : null,
        hasView:  viewMatch  ? "True" : null,
    };
}

export async function searchActiveListings(filters: PropertyFilters, page = 1, limit = 10) {
    const offset = (page - 1) * limit;
    let sql = `
        SELECT
        L_ListingID, L_DisplayId, L_Address, L_City, L_Zip,
        L_SystemPrice AS price, L_Keyword2 AS beds, LM_Dec_3 AS baths,
        LM_Int2_3 AS sqft, L_Type_ AS type, L_Status AS status,
        LMD_MP_Latitude AS lat, LMD_MP_Longitude AS lng,
        YearBuilt, AssociationFee, DaysOnMarket,
        PoolPrivateYN, ViewYN, FireplaceYN, PhotoCount,
        LA1_UserFirstName, LA1_UserLastName, LO1_OrganizationName
        FROM rets_property WHERE L_Status = "Active"
    `;
    const params: any[] = [];
    if (filters.city)     { sql += " AND L_City = ?";           params.push(filters.city); }
    if (filters.maxPrice) { sql += " AND L_SystemPrice <= ?";   params.push(filters.maxPrice); }
    if (filters.beds)     { sql += " AND L_Keyword2 >= ?";      params.push(filters.beds); }
    if (filters.baths)    { sql += " AND LM_Dec_3 >= ?";        params.push(filters.baths); }
    if (filters.sqft)     { sql += " AND LM_Int2_3 >= ?";       params.push(filters.sqft); }
    if (filters.type)     { sql += " AND L_Type_ = ?";          params.push(filters.type); }
    if (filters.pool)     { sql += " AND PoolPrivateYN = ?";    params.push(filters.pool); }
    if (filters.hasView)  { sql += " AND ViewYN = ?";           params.push(filters.hasView); }
    sql += " ORDER BY L_SystemPrice ASC LIMIT ? OFFSET ?";
    params.push(limit, offset); 
    return query<ListingRow>(sql, params);
}

export async function getSoldComps(city: string, months = 12) {
    const sql = `
        SELECT
        ListingKey, UnparsedAddress, City, CloseDate, ClosePrice,
        OriginalListPrice, ListPrice, DaysOnMarket,
        BedroomsTotal, BathroomsTotalInteger, LivingArea,
        PropertyType, PropertySubType, YearBuilt,
        ListAgentFullName, ListOfficeName, BuyerOfficeName
        FROM california_sold
        WHERE City = ?
        AND CloseDate >= DATE_SUB(CURDATE(), INTERVAL ? MONTH)
        AND PropertyType = "Residential"
        ORDER BY CloseDate DESC
        LIMIT 50
    `;
    return query<SoldRow>(sql, [city, months]);
}


//Types for the sql query
interface ListingRow {
    L_ListingID: string, 
    L_DisplayId: string, 
    L_Address: string, 
    L_City: string, 
    L_Zip: string,
    price: number, 
    beds: number, 
    baths: number,
    sqft: number, 
    type: string, 
    status: string,
    lat: number, 
    lng: number,
    YearBuilt: number, 
    AssociationFee: number, 
    DaysOnMarket: number,
    PoolPrivateYN: string, 
    ViewYN: string, 
    FireplaceYN: string, 
    PhotoCount: number,
    LA1_UserFirstName: string, 
    LA1_UserLastName: string, 
    LO1_OrganizationName:  string
}

interface SoldRow {
    ListingKey: string, 
    UnparsedAddress: string, 
    City: string, 
    CloseDate: string, 
    ClosePrice: number,
    OriginalListPrice: number, 
    ListPrice: number, 
    DaysOnMarket: number,
    BedroomsTotal: number, 
    BathroomsTotalInteger: number, 
    LivingArea: number,
    PropertyType: string, 
    PropertySubType: string, 
    YearBuilt: number,
    ListAgentFullName: string, 
    ListOfficeName: string, 
    BuyerOfficeName: string
}

async function main(): Promise<void> {
  const transport = new StdioServerTransport();
  await server.connect(transport);
}

main().catch((error) => {
  console.error("Failed to start MCP server:", error);
  process.exit(1);
});