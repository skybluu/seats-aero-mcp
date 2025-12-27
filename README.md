# Seats.aero MCP Server

This FastMCP server exposes curated tools for Seats.aero's Partner API.

## Setup

1. Install dependencies (recommend a virtual environment):

   ```bash
   cd seats_aero_mcp
   pip install -r requirements.txt
   ```

2. Export your partner token (from the Seats.aero dashboard):

   ```bash
   export SEATS_AERO_PARTNER_TOKEN="pro_xxx"
   ```

3. Run the server via FastMCP's entry point:

   ```bash
   python server.py
   ```

### Running via npm (npx)

After publishing this package to npm (see Publishing section below), the server can be
launched the same way Claude invokes the `nitan` MCP:

```bash
npx -y @haochengf/seats-aero-mcp
```

The CLI bootstraps an isolated Python virtual environment inside the package, installs
`requirements.txt`, and executes `server.py`. Provide your Seats token through the
standard `SEATS_AERO_PARTNER_TOKEN` environment variable.

## Tools

| Tool | Description |
| --- | --- |
| `seats_cached_search` | Cached availability search across origin/destination pairs. |
| `seats_bulk_availability` | High-volume scan for a specific mileage program. |
| `seats_list_routes` | Lists normalized routes tracked by Seats.aero. |
| `seats_trip_details` | Retrieves flight-level segments for a cached availability ID. |

Each tool accepts `response_format` (`markdown` or `json`) and enforces validation via
Pydantic models. Markdown responses are truncated at ~25k characters with clear guidance.

## Publishing

1. Ensure the package metadata in `package.json` (name, version, description, author)
   is correct for your npm scope.
2. Commit the latest changes and push to GitHub (see below).
3. Log in to npm (`npm login`) and publish:

   ```bash
   npm publish --access public
   ```

4. Update Claude Desktop's `claude_desktop_config.json` to add:

   ```json
   {
     "mcpServers": {
       "seats_aero": {
         "command": "npx",
         "args": ["-y", "@haochengf/seats-aero-mcp"],
         "env": {
           "SEATS_AERO_PARTNER_TOKEN": "pro_xxx"
         }
       }
     }
   }
   ```

### GitHub

Inside this folder:

```bash
git init
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin git@github.com:<username>/seats-aero-mcp.git
git push -u origin main
```

Replace `<username>` with your GitHub handle. Once the repo exists, you can set up CI to
run linting, publish to npm, etc.
