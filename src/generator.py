# src/generator.py
import logging
from aiohttp import web
from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine
from src.models import PowerSource, PowerSourceType, PowerStateChange, StateChangeType
from src.notify import notify_state_change
import asyncio
import datetime

DB_URL = "mysql+pymysql://user:password@localhost/power_herald"
engine = create_engine(DB_URL)
Session = sessionmaker(bind=engine)

async def handle_generator_command(request):
    """Handle generator start/stop commands
    POST body: {"source_name": "Generator_1", "command": "start"|"stop"}
    """
    data = await request.json()
    source_name = data.get("source_name")
    command = data.get("command")  # 'start' or 'stop'
    
    if command not in ["start", "stop"]:
        return web.json_response({"error": "Invalid command"}, status=400)
    
    session = Session()
    source = session.query(PowerSource).filter_by(name=source_name, type=PowerSourceType.GENERATOR, enabled=True).first()
    if not source:
        session.close()
        return web.json_response({"error": "Generator source not found"}, status=404)
    
    new_state = StateChangeType.ONLINE if command == "start" else StateChangeType.OFFLINE
    last_state = session.query(PowerStateChange).filter_by(source_id=source.id).order_by(PowerStateChange.timestamp.desc()).first()
    
    if not last_state or last_state.state != new_state:
        state_change = PowerStateChange(
            source_id=source.id,
            state=new_state,
            timestamp=datetime.datetime.utcnow()
        )
        session.add(state_change)
        session.commit()
        logging.info(f"Generator {source.name} command: {command}")
        
        # Trigger notifications
        try:
            asyncio.create_task(notify_state_change(state_change))
        except Exception as e:
            logging.warning(f"Notification failed: {e}")
    
    session.close()
    return web.json_response({"status": "ok"})

def create_app():
    app = web.Application()
    app.router.add_post("/generator", handle_generator_command)
    return app

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    app = create_app()
    web.run_app(app, port=8082)
