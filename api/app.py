import os
import base64, hashlib, hmac, jwt, uuid, json
from pathlib import Path
from typing import Optional, Dict, Any
from fastapi import FastAPI, Request, Depends, HTTPException, Response, UploadFile, File, Query
from fastapi.responses import RedirectResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from jwt import PyJWKClient
from botocore.exceptions import ClientError
import boto3
import math
import time
from s3_utils import put_bytes, presign_get
from sqs_utils import send_task


# ========= Env / Config =========
REGION = os.getenv("AWS_REGION", "ap-southeast-2")
USER_POOL_ID = os.getenv("COGNITO_USER_POOL_ID", "ap-southeast-2_P8ai1eWIN")
CLIENT_ID = os.getenv("COGNITO_CLIENT_ID", "lq7lk6intofk5rf3id0rrc61")
CLIENT_SECRET = os.getenv("COGNITO_CLIENT_SECRET", "1gs1jj4gho4vjm3to6and97e08q2mb1a2qn4e57ru37qupbsrvmb")
FRONTEND_ORIGINS = [o.strip() for o in os.getenv(
    "FRONTEND_ORIGINS",
    "http://127.0.0.1:8000,http://localhost:8000,https://maxgo.cab432.com"
).split(",") if o.strip()]
COOKIE_NAME = "id_token"
COOKIE_MAX_AGE = 3600
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
JWKS_URL = f"https://cognito-idp.{REGION}.amazonaws.com/{USER_POOL_ID}/.well-known/jwks.json"
BUCKET = "maxgo-cab432-2025"
QUEUE_URL = "https://sqs.ap-southeast-2.amazonaws.com/901444280953/image-processing-queue-n11543027"

# ========= App / Middleware =========
app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=FRONTEND_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR), html=False), name="static")

# ========= Cognito / JWT =========
jwks_client = PyJWKClient(JWKS_URL)
cognito = boto3.client("cognito-idp", region_name=REGION)

def verify_id_token(token: str):
    signing_key = jwks_client.get_signing_key_from_jwt(token)
    return jwt.decode(token, signing_key.key, algorithms=["RS256"], audience=CLIENT_ID)

def current_user(request: Request):
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(401, "Missing token")
    try:
        return verify_id_token(token)
    except:
        raise HTTPException(401, "Invalid token")

# ========= Helpers =========
def secret_hash(username: str) -> str:
    msg = username + CLIENT_ID
    dig = hmac.new(CLIENT_SECRET.encode(), msg.encode(), hashlib.sha256).digest()
    return base64.b64encode(dig).decode()

class AuthRequest(BaseModel):
    email: str
    password: str
    is_admin: bool = False

def client_error_to_http(e: ClientError) -> HTTPException:
    code = e.response.get("Error", {}).get("Code", "ClientError")
    msg = e.response.get("Error", {}).get("Message", "Request failed")
    friendly = {
        "NotAuthorizedException": "Invalid credentials.",
        "UserNotConfirmedException": "Account not confirmed. Check your email.",
        "UsernameExistsException": "That email is already registered.",
        "InvalidPasswordException": "Password does not meet the policy.",
        "InvalidParameterException": msg,
    }.get(code, f"{code}: {msg}")
    return HTTPException(400, friendly)

def make_auth_cookie(resp: Response, token: str):
    resp.set_cookie(
        COOKIE_NAME, token,
        httponly=True,
        max_age=COOKIE_MAX_AGE,
        samesite="lax",
        secure=False,
        path="/"
    )

def redirect_with_cookie(id_token: str, role: str) -> Response:
    target = "/admin.html" if role == "admin" else "/user.html"
    resp = RedirectResponse(target, status_code=302)
    make_auth_cookie(resp, id_token)
    return resp

# ========= S3 / SQS =========
s3 = boto3.client("s3", region_name=REGION)
sqs = boto3.client("sqs", region_name=REGION)

# ========= Routes =========
@app.get("/")
def root():
    return FileResponse(FRONTEND_DIR / "login.html")

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/logout")
def logout():
    resp = RedirectResponse("/")
    resp.delete_cookie(COOKIE_NAME, path="/")
    return resp

@app.options("/auth/login")
def opt_login(): return Response(status_code=204)

@app.options("/auth/signup")
def opt_signup(): return Response(status_code=204)

@app.options("/upload")
def opt_upload(): return Response(status_code=204)

@app.get("/scale-test")
def scale_test():
    start = time.time()
    MAX = 10000000  # ← Reduced from 1e9 to 1e7
    for i in range(1, MAX + 1):
        dummy = math.log(i)
    timing = time.time() - start
    return {"status": "load generated", "timing_ms": timing * 1000}

# --- SIGNUP ---
@app.post("/auth/signup")
def signup(req: AuthRequest):
    try:
        attrs = [{"Name": "email", "Value": req.email}]
        if req.is_admin:
            attrs.append({"Name": "custom:role", "Value": "admin"})
        cognito.sign_up(
            ClientId=CLIENT_ID,
            SecretHash=secret_hash(req.email),
            Username=req.email,
            Password=req.password,
            UserAttributes=attrs,
        )
        return {"message": "Check email for verification"}
    except ClientError as e:
        raise client_error_to_http(e)

# --- LOGIN ---
@app.post("/auth/login")
def login(req: AuthRequest):
    try:
        auth = cognito.initiate_auth(
            ClientId=CLIENT_ID,
            AuthFlow="USER_PASSWORD_AUTH",
            AuthParameters={
                "USERNAME": req.email,
                "PASSWORD": req.password,
                "SECRET_HASH": secret_hash(req.email),
            },
        )
        id_token = auth["AuthenticationResult"]["IdToken"]
        payload = verify_id_token(id_token)
        role = payload.get("custom:role", "user")
        return redirect_with_cookie(id_token, role)
    except ClientError as e:
        raise client_error_to_http(e)

# --- USER UPLOADS ---
@app.get("/user/uploads")
def user_uploads(user=Depends(current_user)):
    prefix = f"uploads/{user['sub']}/"
    items = []
    for obj in s3.list_objects_v2(Bucket=BUCKET, Prefix=prefix).get("Contents", []):
        key = obj["Key"]
        if key.lower().endswith(('.jpg', '.jpeg', '.png')):
            fname = key.split("/")[-1]
            items.append({"key": key, "processedKey": f"processed/{fname}"})
    return {"items": items[:50]}

# --- ADMIN UPLOADS LIST ---
@app.get("/admin/uploads")
def admin_uploads(mine: int = 0, user=Depends(current_user)):
    if user.get("custom:role") != "admin":
        raise HTTPException(403, "Admin only")
    prefix = f"uploads/{user['sub']}/" if mine else "uploads/"
    items = []
    for obj in s3.list_objects_v2(Bucket=BUCKET, Prefix=prefix).get("Contents", []):
        key = obj["Key"]
        if key.lower().endswith(('.jpg', '.jpeg', '.png')):
            fname = key.split("/")[-1]
            items.append({"key": key, "processedKey": f"processed/{fname}"})
    return {"items": items[:100]}

# --- ADMIN DELETE ---
@app.post("/admin/delete")
def admin_delete(body: Dict[str, Any], user=Depends(current_user)):
    if user.get("custom:role") != "admin":
        raise HTTPException(403, "Admin only")
    key = body.get("key")
    if not key or not key.startswith("uploads/"):
        raise HTTPException(400, "Invalid key")
    s3.delete_object(Bucket=BUCKET, Key=key)
    fname = key.split("/")[-1]
    s3.delete_object(Bucket=BUCKET, Key=f"processed/{fname}")
    return {"status": "deleted"}

# --- ADMIN REQUEUE (supports mode + params) ---
class AdminRequeueBody(BaseModel):
    key: str
    mode: Optional[str] = "grayscale"
    params: Optional[Dict[str, Any]] = None

@app.post("/admin/requeue")
def admin_requeue(body: AdminRequeueBody, user=Depends(current_user)):
    if user.get("custom:role") != "admin":
        raise HTTPException(403, "Admin only")
    if not body.key or not body.key.startswith("uploads/"):
        raise HTTPException(400, "Invalid key")
    mode = (body.mode or "grayscale").lower()
    params = body.params or {}
    msg = {"key": body.key, "mode": mode, "params": params, "owner": user.get("email")}
    sqs.send_message(QueueUrl=QUEUE_URL, MessageBody=json.dumps(msg))
    return {"status": "queued", "mode": mode, "params": params}

# --- UPLOAD + SQS (ALL FILTERS) ---
@app.post("/upload")
async def upload(
    file: UploadFile = File(...),
    mode: str = Query("grayscale"),
    width: Optional[int] = Query(None),
    height: Optional[int] = Query(None),
    deg: Optional[int] = Query(None),
    text: Optional[str] = Query(None),
    user=Depends(current_user),
):
    ext = file.filename.split(".")[-1].lower()
    key = f"uploads/{user['sub']}/{uuid.uuid4().hex[:12]}.{ext}"
    s3.upload_fileobj(file.file, BUCKET, key)

    mode = (mode or "grayscale").lower()
    message: Dict[str, Any] = {"key": key, "mode": mode, "params": {}}
    if mode == "resize" and (width or height):
        if width is not None:  message["params"]["width"] = width
        if height is not None: message["params"]["height"] = height
    elif mode == "rotate" and deg is not None:
        message["params"]["deg"] = deg
    elif mode == "watermark" and text:
        message["params"]["text"] = text
    elif mode == "thumb":
        message["params"]["width"] = 256
        message["params"]["height"] = 256

    sqs.send_message(QueueUrl=QUEUE_URL, MessageBody=json.dumps(message))

    fname = key.split("/")[-1]
    return {
        "status": "queued",
        "key": key,
        "original_url": f"/files/{key}",
        "processed_url": f"/files/processed/{fname}",
    }

# --- SIGNED READS ---
@app.get("/files/{path:path}")
def get_file(path: str, user=Depends(current_user)):
    url = s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": BUCKET, "Key": path},
        ExpiresIn=3600
    )
    return RedirectResponse(url)

# Protected API
@app.get("/me")
def me(user=Depends(current_user)):
    return {"email": user.get("email"), "role": user.get("custom:role", "user")}

# Serve HTML (must be last)
app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
