
import os
import sys
import uvicorn

# Ensure we can import from backend dir
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from mcp_server import mcp

def main():
    """
    Run the Nocturne Memory MCP server using SSE (Server-Sent Events) transport.
    This is required for clients that don't support stdio (like some web-based tools).
    """
    print("Initializing Nocturne Memory SSE Server...")
    
    # Create the Starlette app for SSE
    # The default mount path is usually /sse or /
    # mcp.sse_app() creates an app that serves /sse and /messages
    app = mcp.sse_app("/sse")
    
    port = int(os.getenv("PORT", 8000))
    host = os.getenv("HOST", "0.0.0.0")
    
    print(f"Starting SSE Server on http://{host}:{port}")
    print(f"SSE Endpoint: http://{host}:{port}/sse")
    
    uvicorn.run(app, host=host, port=port)

if __name__ == "__main__":
    main()
