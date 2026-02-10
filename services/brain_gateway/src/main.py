from fastapi import FastAPI, HTTPException, status, Request
from fastapi.responses import JSONResponse
import logging
import time

from config import settings
from schemas import validator
from ai_client import ai_client

##TRIGGER 

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("brain_gateway")

app = FastAPI(title=settings.app_name, version="1.0.0")

@app.on_event("startup")
async def startup_event():
    # Verify schemas load correctly on startup
    logger.info(f"Loading contracts from {validator.contracts_dir}")
    try:
        if validator.request_schema and validator.response_schema:
            logger.info("Schemas loaded successfully.")
    except Exception as e:
        logger.fatal(f"Failed to load schemas: {e}")
        raise e

@app.post("/v1/brain/complete", status_code=200)
async def complete_analysis(request: Request):
    """
    Main endpoint:
    1. Parse and Validate AIRequest
    2. Call LLM
    3. Validate and Return AIResponse
    """
    try:
        # 1. Parse JSON
        body = await request.json()
    except Exception:
         raise HTTPException(status_code=400, detail="Invalid JSON body")

    # 2. Validate Request Schema
    try:
        validator.validate_request(body)
    except ValueError as e:
        logger.warning(f"Request validation failed: {e}")
        raise HTTPException(
            status_code=422,
            detail=f"Schema Validation Error: {str(e)}"
        )

    # 3. Call AI Client
    try:
        logger.info(f"Processing request {body.get('meta', {}).get('requestId')}")
        ai_response = await ai_client.generate_response(body)
    except RuntimeError as e:
        logger.error(f"Upstream error: {e}")
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        logger.error(f"Internal error: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error")

    # 4. Validate Response Schema
    try:
        validator.validate_response(ai_response)
    except RuntimeError as e:
        # If the LLM returns invalid data (hallucination), we consider it a Bad Gateway / Upstream Error
        logger.error(f"Response validation failed: {e}")
        raise HTTPException(
            status_code=502,
            detail=f"LLM Output Validation Error: {str(e)}"
        )

    return ai_response

@app.get("/health")
def health_check():
    return {"status": "ok"}
