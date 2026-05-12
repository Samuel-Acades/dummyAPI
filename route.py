from fastapi import APIRouter, HTTPException, Depends
from fastapi.security.api_key import APIKeyHeader
from database import database
from pydantic import BaseModel, Field
from datetime import date
from typing import Optional

router = APIRouter()

# --- SECURITY ---
API_KEY = "key" 
api_key_header = APIKeyHeader(name="X-API-KEY", auto_error=False)

async def get_api_key(header_key: str = Depends(api_key_header)):
    if header_key == API_KEY:
        return header_key
    raise HTTPException(status_code=403, detail="Unauthorized: Invalid API Key")

# --- SCHEMAS (CONTRACTS) ---

class FarmRecordCreate(BaseModel):
    record_date: Optional[date] = None
    mode_of_record: str  # e.g., "GPS", "Manual", "Sensor"
    record_type: str    # e.g., "Planting", "Harvest", "Land Prep"
    farm_size_hectares: Optional[float] = None
    crop_type: Optional[str] = None

class UserOnboard(BaseModel):
    """Frictionless registration: No National ID allowed yet."""
    fullname: str
    phonenumber: Optional[str] = None
    crops_grown: Optional[str] = None
    farm_location: Optional[str] = None
    primary_goal: Optional[str] = None

class UserUpdate(BaseModel):
    """The 'Verification' stage: Adds ID and Trust Points."""
    national_id: Optional[str] = None
    # national_id_pts: Optional[int] = Field(None, ge=0, le=20)
    # verify_landsize_pts: Optional[int] = Field(None, ge=0, le=20)
    # link_mobile_money_pts: Optional[int] = Field(None, ge=0, le=20)
    # training_agri_skills_pts: Optional[int] = Field(None, ge=0, le=20)
    # app_interactivity_pts: Optional[int] = Field(None, ge=0, le=20)

class DashboardResponse(BaseModel):
    user_name: str
    user_id: Optional[str] = None # Matches national_id in the view
    crops_grown: Optional[str] = None
    years_active: int
    financial_status: str

# --- API ROUTES ---

@router.post("/onboard")
async def onboard_user(user: UserOnboard):
    """
    Step 1: Simple registration into the 'users' table.
    No points entry is created yet because we lack a National ID.
    """
    try:
        # Format name to Title Case (First letter Caps) before saving
        formatted_name = user.fullname.strip().title()
        
        query = """
            INSERT INTO users (fullname, phonenumber, crops_grown, farm_location, primary_goal)
            VALUES (:fullname, :phonenumber, :crops_grown, :farm_location, :primary_goal)
        """
        values = user.model_dump()
        values["fullname"] = formatted_name # Overwrite with clean name
        await database.execute(query, values=values)
        return {"status": "success", "message": f"User {formatted_name} created."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Registration Failed: {str(e)}")

@router.patch("/user/{identifier}/update", dependencies=[Depends(get_api_key)])
async def update_farmer(identifier: str, data: UserUpdate):
    full_data = data.model_dump(exclude_unset=True)
    new_id = full_data.get("national_id")
    
    try:
        async with database.transaction():
            # 1. Locate user using UUID (Primary) or Name/National ID (Fallback)
            u_query = """
                SELECT user_id, fullname, national_id 
                FROM users 
                WHERE CAST(user_id AS TEXT) = :id 
                OR LOWER(fullname) = LOWER(:id) 
                OR national_id = :id 
                LIMIT 1
            """
            user = await database.fetch_one(u_query, {"id": identifier})
            
            if not user:
                raise HTTPException(status_code=404, detail="User not found")

            target_uuid = user['user_id']

            # 2. National ID Verification & CRB Cross-check
            if new_id:
                crb_query = "SELECT fullname FROM crb_data WHERE national_id = :nid"
                crb_rec = await database.fetch_one(crb_query, {"nid": new_id})

                # Space-safe and Case-insensitive verification
                if crb_rec:
                    user_name_clean = user['fullname'].strip().lower()
                    crb_name_clean = crb_rec['fullname'].strip().lower()
                    
                    if crb_name_clean != user_name_clean:
                        raise HTTPException(
                            status_code=400, 
                            detail=f"Identity mismatch: ID belongs to {crb_rec['fullname']}"
                        )

                # 3. Update User Table with the new National ID
                await database.execute(
                    "UPDATE users SET national_id = :nid WHERE user_id = :uid",
                    {"nid": new_id, "uid": target_uuid}
                )

            # 4. Upsert Points Row (Linked to UUID)
            # This ensures the row exists even if onboard didn't create it
            await database.execute(
                "INSERT INTO points (user_id) VALUES (:uid) ON CONFLICT (user_id) DO NOTHING",
                {"uid": target_uuid}
            )
            # Whenever the user opens the app or logs in
            await database.execute(
                "UPDATE users SET last_login = NOW() WHERE user_id = :uid", 
                {"uid": target_uuid}
            )

            # 5. Apply the Reward Points to the UUID-based row
            points_payload = {k: v for k, v in full_data.items() if k != "national_id"}
            
            if points_payload:
                set_clause = ", ".join([f"{k} = :{k}" for k in points_payload.keys()])
                p_query = f"UPDATE points SET {set_clause} WHERE user_id = :uid"
                points_payload["uid"] = target_uuid
                await database.execute(p_query, values=points_payload)

        return {"status": "success", "message": f"Updated profile for {user['fullname']}"}

    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"Error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error during update")
    
@router.post("/user/{identifier}/farm-records", dependencies=[Depends(get_api_key)])
async def add_farm_record(identifier: str, record: FarmRecordCreate):
    try:
        async with database.transaction():
            # 1. Identify the user (using UUID, Phone, or Name)
            u_query = """
                SELECT user_id FROM users 
                WHERE CAST(user_id AS TEXT) = :id 
                OR phonenumber = :id 
                LIMIT 1
            """
            user = await database.fetch_one(u_query, {"id": identifier})
            
            if not user:
                raise HTTPException(status_code=404, detail="User not found")

            # 2. Insert the record into farm_records
            # The Trigger we wrote will automatically fire after this insert!
            r_query = """
                INSERT INTO farm_records (
                    user_id, 
                    record_date, 
                    mode_of_record, 
                    record_type, 
                    farm_size_hectares, 
                    crop_type
                )
                VALUES (:uid, :rdate, :mode, :rtype, :size, :crop)
                RETURNING record_id
            """
            values = {
                "uid": user['user_id'],
                "rdate": record.record_date or date.today(),
                "mode": record.mode_of_record,
                "rtype": record.record_type,
                "size": record.farm_size_hectares,
                "crop": record.crop_type
            }
            
            record_id = await database.execute(r_query, values=values)

        return {
            "status": "success", 
            "message": "Farm record logged. Trust points updated.",
            "record_id": record_id
        }

    except Exception as e:
        print(f"Error logging farm record: {e}")
        raise HTTPException(status_code=500, detail="Could not save farm record")
    

@router.get("/user/{identifier}/farm-records", dependencies=[Depends(get_api_key)])
async def get_farm_records(identifier: str):
    try:
        # 1. Identify the user
        u_query = "SELECT user_id FROM users WHERE CAST(user_id AS TEXT) = :id OR phonenumber = :id LIMIT 1"
        user = await database.fetch_one(u_query, {"id": identifier})
        
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        # 2. Fetch all their records
        r_query = """
            SELECT record_id, record_date, mode_of_record, record_type, farm_size_hectares, crop_type 
            FROM farm_records 
            WHERE user_id = :uid 
            ORDER BY record_date DESC
        """
        records = await database.fetch_all(r_query, {"uid": user['user_id']})

        return {
            "status": "success",
            "count": len(records),
            "data": records
        }

    except Exception as e:
        print(f"Error fetching records: {e}")
        raise HTTPException(status_code=500, detail="Could not retrieve farm records")

@router.get("/dashboard/{identifier}", response_model=DashboardResponse)
async def get_dashboard(identifier: str):
    """
    Retrieves the final status by joining Users, Points, and CRB via the SQL View.
    """
    query = """
        SELECT * FROM farmer_status_summary 
        WHERE user_name = :id OR user_id = :id 
        LIMIT 1
    """
    row = await database.fetch_one(query, values={"id": identifier})
    if not row:
        raise HTTPException(status_code=404, detail="Farmer record not found")
    return dict(row)