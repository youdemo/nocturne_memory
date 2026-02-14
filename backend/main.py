from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from api import review_router, browse_router, maintenance_router
from db import get_sqlite_client, close_sqlite_client


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时
    print("Memory API starting...")
    
    # Initialize SQLite
    try:
        sqlite_client = get_sqlite_client()
        await sqlite_client.init_db()
        print("SQLite database initialized.")
    except Exception as e:
        print(f"Failed to initialize SQLite: {e}")
    
    yield
    
    # 关闭时
    print("Closing database connections...")
    await close_sqlite_client()


app = FastAPI(
    title="Knowledge Graph API",
    description="AI长期记忆知识图谱后端",
    version="1.0.1",
    lifespan=lifespan
)

# CORS设置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 开发环境，生产环境需要限制
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(review_router)
app.include_router(browse_router)
app.include_router(maintenance_router)


@app.get("/")
async def root():
    """根路径"""
    return {
        "message": "Knowledge Graph API",
        "version": "1.0.1",
        "docs": "/docs"
    }


@app.get("/health")
async def health():
    """健康检查"""
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
