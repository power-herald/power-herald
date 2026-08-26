# src/active_probe.py
import asyncio
import logging
from aiohttp import web
from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine
from src.models import PowerSource, PowerSourceType, StateChangeType
import datetime
from src.config import get_config
from src.state_store import record_state
from src.lifecycle import use_stop_event

config = get_config()
logger = logging.getLogger("active-prober")
logging.getLogger("aiohttp.access").setLevel(logging.WARNING)

engine = create_engine(config.db_url)
Session = sessionmaker(bind=engine)

@web.middleware
async def cors_middleware(request, handler):
    try:
        if request.method == "OPTIONS":
            response = web.Response(status=204)
        else:
            response = await handler(request)
    except web.HTTPException as error:
        response = error
    except Exception:
        logger.exception("Unhandled error while processing %s %s", request.method, request.path)
        response = web.json_response({"error": "Internal server error"}, status=500)
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    response.headers["Access-Control-Max-Age"] = "86400"
    return response

async def handle_active_ping(request):
    data = await request.json()
    source_name = data.get("name")
    state = data.get("state")  # 'online' or 'offline'
    logger.debug("Ping received from %s: source=%s, state=%s", request.remote, source_name, state)
    with Session() as session:
        source = session.query(PowerSource).filter_by(name=source_name, type=PowerSourceType.ACTIVE, enabled=True).first()
        from src.maintenance import is_maintenance
        maintenance, _ = is_maintenance(source.id if source else None)
        if maintenance:
            logger.warning("Active ping rejected for %s: maintenance mode enabled", source_name)
            return web.json_response({"error": "Maintenance mode enabled"}, status=403)
        if not source:
            logger.warning("Active ping rejected: active source not found or disabled: %s", source_name)
            return web.json_response({"error": "Source not found or not active"}, status=404)
        try:
            state_enum = StateChangeType(state)
        except Exception:
            logger.warning("Active ping rejected for %s: invalid state=%s", source_name, state)
            return web.json_response({"error": "Invalid state"}, status=400)
        timestamp = config.now()
        record_state(session, source.id, state_enum, timestamp)
        session.commit()
        logger.info("Source %s is %s", source.name, state_enum.value)
        return web.json_response({"status": "ok"})

def create_app():
    app = web.Application(middlewares=[cors_middleware])
    app.router.add_post(config.active_probe_endpoint, handle_active_ping)
    return app

async def main(stop_event=None):
    stop_event = use_stop_event(stop_event)

    app = create_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, config.active_probe_address, config.active_probe_port)
    try:
        await site.start()
        logger.info("Active probe started on %s:%d", config.active_probe_address, config.active_probe_port)
        await stop_event.wait()
        logger.info("Shutdown signal received")
    finally:
        await runner.cleanup()
        engine.dispose()

if __name__ == "__main__":
    asyncio.run(main())
