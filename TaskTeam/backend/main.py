from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import or_, and_
from typing import List
from datetime import datetime
import os

from database import engine, get_db, Base
from models import User, Task, Priority, TaskStatus, Project, TeamMember, Team
from schemas import (
    UserCreate, UserLogin, UserResponse, Token, 
    TaskCreate, TaskUpdate, TaskResponse,
    ProjectCreate, ProjectResponse, TeamMemberCreate, TeamMemberResponse, UserSelect,
    TeamCreate, TeamResponse
)
from auth import authenticate_user, create_access_token, get_current_user, get_password_hash

# Создаем таблицы
Base.metadata.create_all(bind=engine)

# Создаем приложение
app = FastAPI(
    title="TaskTeam API",
    description="TaskTeam — командная система управления задачами",
    version="1.0.0"
)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files (frontend)
# frontend_path = os.path.join(os.path.dirname(__file__), "..", "frontend")
# if os.path.exists(frontend_path):
#     app.mount("/frontend", StaticFiles(directory=frontend_path), name="frontend")

# ═══════════════════════════════════════════════════
# AUTH ENDPOINTS
# ═══════════════════════════════════════════════════

@app.post("/auth/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(user: UserCreate, db: Session = Depends(get_db)):
    existing_user = db.query(User).filter(User.username == user.username).first()
    
    if existing_user:
        raise HTTPException(status_code=400, detail="Имя пользователя уже занято")
    
    hashed_password = get_password_hash(user.password)
    db_user = User(
        username=user.username,
        hashed_password=hashed_password,
        created_at=datetime.utcnow()
    )
    
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    
    return db_user

@app.post("/auth/login", response_model=Token)
async def login(user: UserLogin, db: Session = Depends(get_db)):
    db_user = authenticate_user(db, user.username, user.password)
    
    if not db_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверное имя пользователя или пароль",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    access_token = create_access_token(data={"sub": db_user.username})
    
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "username": db_user.username
    }

@app.get("/auth/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)):
    return current_user

@app.put("/auth/me", response_model=UserResponse)
async def update_profile(
    profile_update: dict,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # Обновляем username если передан
    if "username" in profile_update and profile_update["username"]:
        # Проверяем что username не занят другим пользователем
        existing = db.query(User).filter(
            User.username == profile_update["username"],
            User.id != current_user.id
        ).first()
        if existing:
            raise HTTPException(status_code=400, detail="Имя пользователя уже занято")
        current_user.username = profile_update["username"]

    # Обновляем пароль если передан
    if "password" in profile_update and profile_update["password"]:
        current_user.hashed_password = get_password_hash(profile_update["password"])

    db.commit()
    db.refresh(current_user)
    return current_user

@app.get("/users/", response_model=List[UserSelect])
async def get_all_users(username: str = None, db: Session = Depends(get_db)):
    query = db.query(User)
    if username:
        # case-insensitive search, exact or partial
        query = query.filter(User.username.ilike(f"%{username}%"))
    users = query.all()
    return users

# ═══════════════════════════════════════════════════
# TEAM ENDPOINTS
# ═══════════════════════════════════════════════════

@app.post("/teams/", response_model=TeamResponse, status_code=status.HTTP_201_CREATED)
async def create_team(
    team: TeamCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    db_team = Team(
        name=team.name,
        description=team.description,
        owner_id=current_user.id,
        created_at=datetime.utcnow()
    )
    
    db.add(db_team)
    db.commit()
    db.refresh(db_team)
    
    # Добавляем создателя как владельца команды
    team_member = TeamMember(
        user_id=current_user.id,
        team_id=db_team.id,
        role="owner"
    )
    db.add(team_member)
    db.commit()
    
    # Формируем правильный ответ с членами команды
    members = db.query(User).join(TeamMember).filter(TeamMember.team_id == db_team.id).all()
    members_out = [UserSelect(id=m.id, username=m.username) for m in members]
    
    return TeamResponse(
        id=db_team.id,
        name=db_team.name,
        description=db_team.description,
        owner_id=db_team.owner_id,
        members=members_out,
        created_at=db_team.created_at
    )

@app.get("/teams/", response_model=List[TeamResponse])
async def get_teams(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # Получаем команды где пользователь владелец или участник
    owned = db.query(Team).filter(Team.owner_id == current_user.id).all()
    member_ids = db.query(TeamMember.team_id).filter(TeamMember.user_id == current_user.id).all()
    member_teams = db.query(Team).filter(Team.id.in_([m[0] for m in member_ids])).all() if member_ids else []
    
    teams = list(set(owned + member_teams))
    
    result = []
    for team in teams:
        # Получаем членов команды
        members = db.query(User).join(TeamMember).filter(TeamMember.team_id == team.id).all()
        members_out = [UserSelect(id=m.id, username=m.username) for m in members]
        
        result.append(TeamResponse(
            id=team.id,
            name=team.name,
            description=team.description,
            owner_id=team.owner_id,
            members=members_out,
            created_at=team.created_at
        ))
    
    return result

@app.get("/teams/{team_id}", response_model=TeamResponse)
async def get_team(
    team_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    team = db.query(Team).filter(Team.id == team_id).first()
    if not team:
        raise HTTPException(status_code=404, detail="Команда не найдена")
    
    # Получаем членов команды
    members = db.query(User).join(TeamMember).filter(TeamMember.team_id == team_id).all()
    members_out = [UserSelect(id=m.id, username=m.username) for m in members]
    
    return TeamResponse(
        id=team.id,
        name=team.name,
        description=team.description,
        owner_id=team.owner_id,
        members=members_out,
        created_at=team.created_at
    )

@app.delete("/teams/{team_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_team(
    team_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    team = db.query(Team).filter(Team.id == team_id).first()
    if not team:
        raise HTTPException(status_code=404, detail="Команда не найдена")
    if team.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Только владелец может удалить команду")

    # удаляем связанные члены и проекты и задачи?
    db.query(TeamMember).filter(TeamMember.team_id == team_id).delete()
    # опционально удаляем проекты команды (и их задачи)
    projects = db.query(Project).filter(Project.team_id == team_id).all()
    for p in projects:
        db.query(Task).filter(Task.project_id == p.id).delete()
    db.query(Project).filter(Project.team_id == team_id).delete()

    db.delete(team)
    db.commit()
    return

@app.post("/teams/{team_id}/members", response_model=TeamMemberResponse)
async def add_team_member(
    team_id: int,
    member: TeamMemberCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    team = db.query(Team).filter(Team.id == team_id).first()
    if not team:
        raise HTTPException(status_code=404, detail="Команда не найдена")
    
    if team.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Только владелец может добавлять участников")
    
    existing_member = db.query(TeamMember).filter(
        TeamMember.team_id == team_id,
        TeamMember.user_id == member.user_id
    ).first()
    
    if existing_member:
        raise HTTPException(status_code=400, detail="Пользователь уже в команде")
    
    db_member = TeamMember(
        user_id=member.user_id,
        team_id=team_id,
        role=member.role
    )
    
    db.add(db_member)
    db.commit()
    db.refresh(db_member)
    
    user = db.query(User).filter(User.id == member.user_id).first()
    
    return {
        "id": db_member.id,
        "user_id": db_member.user_id,
        "username": user.username if user else "Unknown",
        "role": db_member.role,
        "joined_at": db_member.joined_at
    }

@app.get("/teams/{team_id}/members", response_model=List[TeamMemberResponse])
async def get_team_members(
    team_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    members = db.query(TeamMember).filter(TeamMember.team_id == team_id).all()
    
    result = []
    for member in members:
        user = db.query(User).filter(User.id == member.user_id).first()
        result.append({
            "id": member.id,
            "user_id": member.user_id,
            "username": user.username if user else "Unknown",
            "role": member.role,
            "joined_at": member.joined_at
        })
    
    return result


@app.get("/teams/{team_id}/tasks", response_model=List[TaskResponse])
async def get_team_tasks(
    team_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # Проверяем существование команды
    team = db.query(Team).filter(Team.id == team_id).first()
    if not team:
        raise HTTPException(status_code=404, detail="Команда не найдена")

    # Получаем всех участников команды
    members = db.query(TeamMember).filter(TeamMember.team_id == team_id).all()
    member_user_ids = [m.user_id for m in members]

    # Только участники команды и владелец могут смотреть задачи команды
    if current_user.id not in member_user_ids and current_user.id != team.owner_id:
        raise HTTPException(status_code=403, detail="Доступ запрещен")

    # Получаем проекты команды
    projects = db.query(Project).filter(Project.team_id == team_id).all()
    project_ids = [p.id for p in projects]

    # Выбираем задачи, которые:
    # - принадлежат проектам команды
    # - или не привязаны к проекту, но созданы участниками команды
    query = db.query(Task)
    filters = []
    if project_ids:
        filters.append(Task.project_id.in_(project_ids))
    if member_user_ids:
        filters.append(and_(Task.project_id == None, Task.owner_id.in_(member_user_ids)))

    if filters:
        # объединяем условия OR
        query = query.filter(or_(*filters))
    else:
        # если нет проектов и членов (маловероятно) - возвращаем пустой список
        return []

    tasks = query.all()
    return tasks

@app.get("/teams/{team_id}/projects/", response_model=List[ProjectResponse])
async def get_team_projects(
    team_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # Проверяем существование команды
    team = db.query(Team).filter(Team.id == team_id).first()
    if not team:
        raise HTTPException(status_code=404, detail="Команда не найдена")

    # Получаем всех участников команды
    members = db.query(TeamMember).filter(TeamMember.team_id == team_id).all()
    member_user_ids = [m.user_id for m in members]

    # Только участники команды и владелец могут смотреть проекты команды
    if current_user.id not in member_user_ids and current_user.id != team.owner_id:
        raise HTTPException(status_code=403, detail="Доступ запрещен")

    # Получаем проекты команды
    projects = db.query(Project).filter(Project.team_id == team_id).all()
    return projects

@app.delete("/teams/{team_id}/members/{member_id}")
async def remove_team_member(
    team_id: int,
    member_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    team = db.query(Team).filter(Team.id == team_id).first()
    if not team:
        raise HTTPException(status_code=404, detail="Команда не найдена")
    
    if team.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Только владелец может удалять участников")
    
    member = db.query(TeamMember).filter(
        TeamMember.team_id == team_id,
        TeamMember.id == member_id
    ).first()
    
    if not member:
        raise HTTPException(status_code=404, detail="Участник не найден")
    
    db.delete(member)
    db.commit()
    
    return {"message": "Участник удален из команды"}

# ═══════════════════════════════════════════════════
# PROJECT ENDPOINTS
# ═══════════════════════════════════════════════════

@app.post("/projects/", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project(
    project: ProjectCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    db_project = Project(
        name=project.name,
        description=project.description,
        color=project.color,
        owner_id=current_user.id,
        created_at=datetime.utcnow()
    )
    
    db.add(db_project)
    db.commit()
    db.refresh(db_project)
    
    # Добавляем создателя как владельца команды
    team_member = TeamMember(
        user_id=current_user.id,
        project_id=db_project.id,
        role="owner"
    )
    db.add(team_member)
    db.commit()
    
    return db_project

@app.get("/projects/", response_model=List[ProjectResponse])
async def get_projects(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # Получаем проекты где пользователь владелец или участник
    owned = db.query(Project).filter(Project.owner_id == current_user.id).all()
    member_ids = db.query(TeamMember.project_id).filter(TeamMember.user_id == current_user.id).all()
    member_projects = db.query(Project).filter(Project.id.in_([m[0] for m in member_ids])).all()
    
    return list(set(owned + member_projects))

@app.get("/projects/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Проект не найден")
    return project

@app.post("/projects/{project_id}/members", response_model=TeamMemberResponse)
async def add_project_member(
    project_id: int,
    member: TeamMemberCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Проект не найден")
    
    if project.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Только владелец может добавлять участников")
    
    existing_member = db.query(TeamMember).filter(
        TeamMember.project_id == project_id,
        TeamMember.user_id == member.user_id
    ).first()
    
    if existing_member:
        raise HTTPException(status_code=400, detail="Пользователь уже в команде")
    
    db_member = TeamMember(
        user_id=member.user_id,
        project_id=project_id,
        role=member.role
    )
    
    db.add(db_member)
    db.commit()
    db.refresh(db_member)
    
    return db_member

@app.get("/projects/{project_id}/members", response_model=List[TeamMemberResponse])
async def get_project_members(
    project_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    members = db.query(TeamMember).filter(TeamMember.project_id == project_id).all()
    
    result = []
    for member in members:
        user = db.query(User).filter(User.id == member.user_id).first()
        result.append({
            "id": member.id,
            "user_id": member.user_id,
            "username": user.username if user else "Unknown",
            "role": member.role,
            "joined_at": member.joined_at
        })
    
    return result

# ═══════════════════════════════════════════════════
# TASK ENDPOINTS
# ═══════════════════════════════════════════════════

@app.post("/tasks/", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
async def create_task(
    task: TaskCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # Map priority string to enum, case-insensitive
    priority_map = {p.value.lower(): p for p in Priority}
    priority_enum = priority_map.get(task.priority.lower(), Priority.Medium)
    status_enum = getattr(TaskStatus, task.status.upper(), TaskStatus.TODO)
    
    db_task = Task(
        title=task.title,
        description=task.description,
        priority=priority_enum,
        status=status_enum,
        owner_id=current_user.id,
        assignee_id=task.assignee_id,
        tags=task.tags,
        project_id=task.project_id,
        due_date=task.due_date,
        created_at=datetime.utcnow()
    )
    
    db.add(db_task)
    db.commit()
    db.refresh(db_task)
    
    return db_task

@app.get("/tasks/", response_model=List[TaskResponse])
async def get_tasks(
    current_user: User = Depends(get_current_user),
    project_id: int = None,
    db: Session = Depends(get_db)
):
    query = db.query(Task)

    if project_id:
        # если указан проект, возвращаем задачи этого проекта
        query = query.filter(Task.project_id == project_id)
    else:
        # base filters for owner's and assignee's own tasks
        filters = [Task.owner_id == current_user.id, Task.assignee_id == current_user.id]

        # добавляем задачи, связанные с командами пользователя
        # сначала получаем все команды, в которых состоит пользователь
        team_ids = [tid for (tid,) in db.query(TeamMember.team_id).filter(TeamMember.user_id == current_user.id).all()]
        if team_ids:
            # проекты этих команд
            project_ids = [pid for (pid,) in db.query(Project.id).filter(Project.team_id.in_(team_ids)).all()]
            if project_ids:
                filters.append(Task.project_id.in_(project_ids))

            # участники этих команд
            member_user_ids = [uid for (uid,) in db.query(TeamMember.user_id).filter(TeamMember.team_id.in_(team_ids)).all()]
            if member_user_ids:
                # также включаем задачи без проекта, созданные участниками команд
                filters.append(and_(Task.project_id == None, Task.owner_id.in_(member_user_ids)))

        # объединяем все условия OR
        query = query.filter(or_(*filters))

    return query.all()

@app.get("/tasks/{task_id}", response_model=TaskResponse)
async def get_task(
    task_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    db_task = db.query(Task).filter(Task.id == task_id).first()
    if not db_task:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    return db_task

@app.put("/tasks/{task_id}", response_model=TaskResponse)
async def update_task(
    task_id: int,
    task: TaskUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    db_task = db.query(Task).filter(Task.id == task_id).first()
    if not db_task:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    
    update_data = task.dict(exclude_unset=True)
    
    if 'priority' in update_data and update_data['priority']:
        # Map priority string to enum, case-insensitive
        priority_map = {p.value.lower(): p for p in Priority}
        db_task.priority = priority_map.get(update_data['priority'].lower(), Priority.Medium)
    if 'status' in update_data and update_data['status']:
        db_task.status = getattr(TaskStatus, update_data['status'].upper(), TaskStatus.TODO)
    
    for key, value in update_data.items():
        if key not in ['priority', 'status']:
            setattr(db_task, key, value)
    
    db.commit()
    db.refresh(db_task)
    
    return db_task

@app.patch("/tasks/{task_id}/status", response_model=TaskResponse)
async def update_task_status(
    task_id: int,
    status_update: dict,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    db_task = db.query(Task).filter(Task.id == task_id).first()
    if not db_task:
        raise HTTPException(status_code=404, detail="Задача не найдена")

    # Determine access: owner, assignee, or any member of the task's team (if project->team)
    allowed_user_ids = {db_task.owner_id}
    if db_task.assignee_id:
        allowed_user_ids.add(db_task.assignee_id)

    team_id = None
    if db_task.project_id:
        proj = db.query(Project).filter(Project.id == db_task.project_id).first()
        if proj and proj.team_id:
            team_id = proj.team_id

    if team_id:
        members = db.query(TeamMember).filter(TeamMember.team_id == team_id).all()
        allowed_user_ids.update([m.user_id for m in members])
        team = db.query(Team).filter(Team.id == team_id).first()
        if team:
            allowed_user_ids.add(team.owner_id)

    # Only allow if current_user is in allowed set
    if current_user.id not in allowed_user_ids:
        raise HTTPException(status_code=403, detail="Доступ запрещен: вы не участник команды задачи")

    new_status = status_update.get('status')
    if not new_status:
        raise HTTPException(status_code=400, detail="Нужно передать новый статус")

    # Assign task to current user if not assigned yet (someone "взял" задачу)
    if not db_task.assignee_id:
        db_task.assignee_id = current_user.id

    # Update status enum (graceful fallback to TODO)
    db_task.status = getattr(TaskStatus, new_status.upper(), TaskStatus.TODO)

    db.commit()
    db.refresh(db_task)

    return db_task

@app.patch("/tasks/{task_id}/assignee", response_model=TaskResponse)
async def assign_task(
    task_id: int,
    assignee_data: dict,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    db_task = db.query(Task).filter(Task.id == task_id).first()
    if not db_task:
        raise HTTPException(status_code=404, detail="Задача не найдена")

    new_assignee_id = assignee_data.get('assignee_id')
    if not new_assignee_id:
        raise HTTPException(status_code=400, detail="Нужно указать assignee_id")

    # Check if new_assignee is user or current_user
    if new_assignee_id != current_user.id:
        raise HTTPException(status_code=403, detail="Можно назначать только себя")

    # Determine access: owner, assignee, or any member of the task's team (if project->team)
    allowed_user_ids = {db_task.owner_id}
    if db_task.assignee_id:
        allowed_user_ids.add(db_task.assignee_id)

    team_id = None
    if db_task.project_id:
        proj = db.query(Project).filter(Project.id == db_task.project_id).first()
        if proj and proj.team_id:
            team_id = proj.team_id

    if team_id:
        members = db.query(TeamMember).filter(TeamMember.team_id == team_id).all()
        allowed_user_ids.update([m.user_id for m in members])
        team = db.query(Team).filter(Team.id == team_id).first()
        if team:
            allowed_user_ids.add(team.owner_id)

    # Также позволяем членам команд, где создатель задачи является членом
    team_ids = [tid for (tid,) in db.query(TeamMember.team_id).filter(TeamMember.user_id == current_user.id).all()]
    if team_ids:
        member_user_ids = [uid for (uid,) in db.query(TeamMember.user_id).filter(TeamMember.team_id.in_(team_ids)).all()]
        if db_task.owner_id in member_user_ids:
            allowed_user_ids.update(member_user_ids)

    # Only allow if current_user is in allowed set
    if current_user.id not in allowed_user_ids:
        raise HTTPException(status_code=403, detail="Доступ запрещен: вы не участник команды задачи")

    # Check if task is already assigned
    if db_task.assignee_id:
        raise HTTPException(status_code=400, detail="Задача уже назначена")

    db_task.assignee_id = new_assignee_id
    db.commit()
    db.refresh(db_task)

    return db_task

@app.delete("/tasks/{task_id}")
async def delete_task(
    task_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    db_task = db.query(Task).filter(Task.id == task_id).first()
    if not db_task:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    
    db.delete(db_task)
    db.commit()
    
    return {"message": "Задача удалена"}

# ═══════════════════════════════════════════════════
# Health check & Root
# ═══════════════════════════════════════════════════

@app.get("/")
async def root():
    return {
        "message": "TaskTeam API",
        "version": "1.0.0",
        "description": "TaskTeam — командная система управления задачами",
        "docs": "/docs",
        "status": "running"
    }

@app.get("/health")
async def health():
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}