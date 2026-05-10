"""
Admin management endpoints.
"""
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, case, or_, String

from app.core.database import get_db
from app.core.deps import get_admin_user
from app.models.models import User, Organization, ParseTask, TaskStatus
from app.schemas.schemas import (
    AdminStatsOut, AdminRecentUser,
    AdminUserOut, AdminUserUpdate, AdminUserListResponse,
    AdminTaskOut, AdminTaskListResponse,
)

router = APIRouter(prefix="/admin", tags=["admin"])


# ── Dashboard stats ─────────────────────────────────────────────────────────
@router.get("/stats", response_model=AdminStatsOut)
async def get_admin_stats(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(get_admin_user),
):
    # Total users
    total_users = (await db.execute(select(func.count(User.id)))).scalar() or 0

    # Total tasks
    total_tasks = (await db.execute(select(func.count(ParseTask.id)))).scalar() or 0

    # Tasks by status
    status_rows = (await db.execute(
        select(ParseTask.status, func.count(ParseTask.id))
        .group_by(ParseTask.status)
    )).all()
    tasks_by_status = {row[0].value if hasattr(row[0], "value") else str(row[0]): row[1] for row in status_rows}

    # Total storage (sum of file_size_bytes)
    total_bytes = (await db.execute(
        select(func.coalesce(func.sum(ParseTask.file_size_bytes), 0))
    )).scalar() or 0
    total_storage_mb = round(total_bytes / (1024 * 1024), 1)

    # Recent users
    recent_rows = (await db.execute(
        select(User.id, User.username, User.email, User.created_at)
        .order_by(User.created_at.desc())
        .limit(5)
    )).all()
    recent_users = [
        AdminRecentUser(id=str(r[0]), username=r[1], email=r[2], created_at=r[3])
        for r in recent_rows
    ]

    return AdminStatsOut(
        total_users=total_users,
        total_tasks=total_tasks,
        tasks_by_status=tasks_by_status,
        total_storage_mb=total_storage_mb,
        recent_users=recent_users,
    )


# ── User management ─────────────────────────────────────────────────────────
@router.get("/users", response_model=AdminUserListResponse)
async def list_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: str = Query("", description="Search by username or email"),
    role: str = Query("", description="Filter by role"),
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(get_admin_user),
):
    query = select(User)
    count_query = select(func.count(User.id))

    if search:
        pattern = f"%{search}%"
        filter_cond = (User.username.ilike(pattern) | User.email.ilike(pattern))
        query = query.where(filter_cond)
        count_query = count_query.where(filter_cond)

    if role:
        if role == "super_admin":
            query = query.where(User.is_superuser == True)
            count_query = count_query.where(User.is_superuser == True)
        else:
            query = query.where(User.role == role, User.is_superuser == False)
            count_query = count_query.where(User.role == role, User.is_superuser == False)

    total = (await db.execute(count_query)).scalar() or 0

    offset = (page - 1) * page_size
    rows = (await db.execute(
        query.order_by(User.created_at.desc()).offset(offset).limit(page_size)
    )).scalars().all()

    items = []
    for u in rows:
        task_count = (await db.execute(
            select(func.count(ParseTask.id)).where(ParseTask.user_id == u.id)
        )).scalar() or 0

        org_name = None
        if u.organization_id:
            org = (await db.execute(
                select(Organization.name).where(Organization.id == u.organization_id)
            )).scalar_one_or_none()
            org_name = org

        items.append(AdminUserOut(
            id=str(u.id),
            email=u.email,
            username=u.username,
            full_name=u.full_name,
            avatar_url=u.avatar_url,
            role=u.role.value if hasattr(u.role, "value") else str(u.role),
            sso_provider=u.sso_provider.value if hasattr(u.sso_provider, "value") else str(u.sso_provider),
            is_active=u.is_active,
            is_superuser=u.is_superuser,
            organization_id=str(u.organization_id) if u.organization_id else None,
            organization_name=org_name,
            created_at=u.created_at,
            last_login_at=u.last_login_at,
            task_count=task_count,
        ))

    return AdminUserListResponse(items=items, total=total, page=page, page_size=page_size)


@router.get("/users/{user_id}", response_model=AdminUserOut)
async def get_user(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(get_admin_user),
):
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    task_count = (await db.execute(
        select(func.count(ParseTask.id)).where(ParseTask.user_id == user.id)
    )).scalar() or 0

    org_name = None
    if user.organization_id:
        org = (await db.execute(
            select(Organization.name).where(Organization.id == user.organization_id)
        )).scalar_one_or_none()
        org_name = org

    return AdminUserOut(
        id=str(user.id),
        email=user.email,
        username=user.username,
        full_name=user.full_name,
        avatar_url=user.avatar_url,
        role=user.role.value if hasattr(user.role, "value") else str(user.role),
        sso_provider=user.sso_provider.value if hasattr(user.sso_provider, "value") else str(user.sso_provider),
        is_active=user.is_active,
        is_superuser=user.is_superuser,
        organization_id=str(user.organization_id) if user.organization_id else None,
        organization_name=org_name,
        created_at=user.created_at,
        last_login_at=user.last_login_at,
        task_count=task_count,
    )


@router.patch("/users/{user_id}", response_model=AdminUserOut)
async def update_user(
    user_id: str,
    payload: AdminUserUpdate,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(get_admin_user),
):
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if user.is_superuser:
        if payload.role is not None:
            raise HTTPException(status_code=400, detail="Cannot change super admin role")
        if payload.is_active is False:
            raise HTTPException(status_code=400, detail="Cannot disable super admin")

    # Prevent demoting the last admin
    if payload.role is not None and payload.role != "admin":
        if user.role == "admin" or user.is_superuser:
            admin_count = (await db.execute(
                select(func.count(User.id)).where(
                    (User.role == "admin") | (User.is_superuser == True)
                )
            )).scalar() or 0
            if admin_count <= 1:
                raise HTTPException(status_code=400, detail="Cannot demote the last admin")

    if payload.role is not None:
        user.role = payload.role
    if payload.is_active is not None:
        user.is_active = payload.is_active
    if payload.organization_id is not None:
        if payload.organization_id == "":
            user.organization_id = None
        else:
            org = (await db.execute(
                select(Organization).where(Organization.id == payload.organization_id)
            )).scalar_one_or_none()
            if not org:
                raise HTTPException(status_code=400, detail="Organization not found")
            user.organization_id = payload.organization_id

    await db.commit()
    await db.refresh(user)

    task_count = (await db.execute(
        select(func.count(ParseTask.id)).where(ParseTask.user_id == user.id)
    )).scalar() or 0

    org_name = None
    if user.organization_id:
        org = (await db.execute(
            select(Organization.name).where(Organization.id == user.organization_id)
        )).scalar_one_or_none()
        org_name = org

    return AdminUserOut(
        id=str(user.id),
        email=user.email,
        username=user.username,
        full_name=user.full_name,
        avatar_url=user.avatar_url,
        role=user.role.value if hasattr(user.role, "value") else str(user.role),
        sso_provider=user.sso_provider.value if hasattr(user.sso_provider, "value") else str(user.sso_provider),
        is_active=user.is_active,
        is_superuser=user.is_superuser,
        organization_id=str(user.organization_id) if user.organization_id else None,
        organization_name=org_name,
        created_at=user.created_at,
        last_login_at=user.last_login_at,
        task_count=task_count,
    )


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(get_admin_user),
):
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if user.id == _admin.id:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")
    if user.is_superuser:
        raise HTTPException(status_code=400, detail="Cannot delete super admin")

    # Prevent deleting the last admin
    if user.role == "admin" or user.is_superuser:
        admin_count = (await db.execute(
            select(func.count(User.id)).where(
                (User.role == "admin") | (User.is_superuser == True)
            )
        )).scalar() or 0
        if admin_count <= 1:
            raise HTTPException(status_code=400, detail="Cannot delete the last admin")

    # Unlink tasks (set user_id to NULL) rather than cascade delete
    await db.execute(
        ParseTask.__table__.update()
        .where(ParseTask.user_id == user_id)
        .values(user_id=None)
    )

    await db.delete(user)
    await db.commit()
    return {"detail": "User deleted"}


# ── Task execution (time-based) ──────────────────────────────────────────────
@router.get("/tasks", response_model=AdminTaskListResponse)
async def list_admin_tasks(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str = Query("", description="Filter by status"),
    user_id: str = Query("", description="Filter by user ID"),
    search: str = Query("", description="Search filename, task ID, username, or email"),
    date_from: str = Query("", description="Start datetime (YYYY-MM-DD or YYYY-MM-DDTHH:mm)"),
    date_to: str = Query("", description="End datetime (YYYY-MM-DD or YYYY-MM-DDTHH:mm)"),
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(get_admin_user),
):
    query = select(ParseTask, User.username).outerjoin(User, ParseTask.user_id == User.id)
    count_query = select(func.count(ParseTask.id)).outerjoin(User, ParseTask.user_id == User.id)

    if status:
        query = query.where(ParseTask.status == status)
        count_query = count_query.where(ParseTask.status == status)

    if user_id:
        query = query.where(ParseTask.user_id == user_id)
        count_query = count_query.where(ParseTask.user_id == user_id)

    search_term = search.strip()
    if search_term:
        pattern = f"%{search_term}%"
        search_filter = or_(
            ParseTask.original_filename.ilike(pattern),
            ParseTask.id.cast(String).ilike(pattern),
            User.username.ilike(pattern),
            User.email.ilike(pattern),
        )
        query = query.where(search_filter)
        count_query = count_query.where(search_filter)

    if date_from:
        try:
            dt_from = datetime.fromisoformat(date_from)
            query = query.where(ParseTask.created_at >= dt_from)
            count_query = count_query.where(ParseTask.created_at >= dt_from)
        except ValueError:
            pass

    if date_to:
        try:
            dt_to = datetime.fromisoformat(date_to)
            if "T" not in date_to and len(date_to) <= 10:
                dt_to = dt_to + timedelta(days=1)
            query = query.where(ParseTask.created_at < dt_to)
            count_query = count_query.where(ParseTask.created_at < dt_to)
        except ValueError:
            pass

    total = (await db.execute(count_query)).scalar() or 0

    offset = (page - 1) * page_size
    rows = (await db.execute(
        query.order_by(ParseTask.created_at.desc()).offset(offset).limit(page_size)
    )).all()

    items = []
    for task, username in rows:
        # Calculate duration
        duration_s = None
        if task.started_at and task.completed_at:
            delta = task.completed_at - task.started_at
            duration_s = max(0, int(delta.total_seconds()))
        elif task.started_at and task.status in (TaskStatus.PROCESSING, TaskStatus.PENDING):
            delta = datetime.now(task.started_at.tzinfo) - task.started_at
            duration_s = max(0, int(delta.total_seconds()))

        items.append(AdminTaskOut(
            id=str(task.id),
            original_filename=task.original_filename,
            file_size_bytes=task.file_size_bytes,
            status=task.status.value if hasattr(task.status, "value") else str(task.status),
            progress=task.progress,
            backend=task.backend,
            username=username,
            created_at=task.created_at,
            started_at=task.started_at,
            completed_at=task.completed_at,
            duration_s=duration_s,
            error_message=task.error_message,
        ))

    return AdminTaskListResponse(items=items, total=total, page=page, page_size=page_size)
