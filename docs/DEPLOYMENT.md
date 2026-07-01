> 项目：宛委·枢忆 OSAgent  
> 版本：v0.2（含 SOTA 对标、记忆安全、自演化与评测增强）  

# 部署指南

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m app.init_db
uvicorn app.main:app --host 127.0.0.1 --port 8765
```
