from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session, joinedload
from typing import List, Dict
from backend.database import get_db, SessionLocal
from backend.auth import get_current_user, decode_token
from backend.models import User, Conversation, ConversationMember, Message
from backend.schemas import ConversationCreate, ConversationOut, MessageCreate, MessageOut, UserBrief

router = APIRouter(prefix="/api/chat", tags=["chat"])

# Simple in-memory connection manager for WebSocket
class ConnectionManager:
    def __init__(self):
        self.active: Dict[int, List[WebSocket]] = {}  # user_id -> websockets

    async def connect(self, user_id: int, websocket: WebSocket):
        await websocket.accept()
        self.active.setdefault(user_id, []).append(websocket)

    def disconnect(self, user_id: int, websocket: WebSocket):
        if user_id in self.active:
            self.active[user_id] = [w for w in self.active[user_id] if w != websocket]
            if not self.active[user_id]:
                del self.active[user_id]

    async def send_to_user(self, user_id: int, data: dict):
        for ws in self.active.get(user_id, []):
            try:
                await ws.send_json(data)
            except Exception:
                pass


manager = ConnectionManager()


@router.get("/conversations", response_model=List[ConversationOut])
async def list_conversations(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    memberships = (
        db.query(ConversationMember)
        .filter(ConversationMember.user_id == current_user.id)
        .all()
    )
    conv_ids = [m.conversation_id for m in memberships]
    if not conv_ids:
        return []

    conversations = (
        db.query(Conversation)
        .options(joinedload(Conversation.members).joinedload(ConversationMember.user))
        .filter(Conversation.id.in_(conv_ids))
        .order_by(Conversation.updated_at.desc())
        .all()
    )

    result = []
    for conv in conversations:
        last_msg = (
            db.query(Message)
            .options(joinedload(Message.sender))
            .filter(Message.conversation_id == conv.id)
            .order_by(Message.created_at.desc())
            .first()
        )
        membership = next((m for m in memberships if m.conversation_id == conv.id), None)
        unread = 0
        if membership and membership.last_read_at:
            unread = (
                db.query(Message)
                .filter(
                    Message.conversation_id == conv.id,
                    Message.created_at > membership.last_read_at,
                    Message.sender_id != current_user.id,
                )
                .count()
            )
        elif membership:
            unread = (
                db.query(Message)
                .filter(Message.conversation_id == conv.id, Message.sender_id != current_user.id)
                .count()
            )

        members = [m.user for m in conv.members]
        result.append(
            ConversationOut(
                id=conv.id,
                title=conv.title,
                is_group=conv.is_group,
                created_at=conv.created_at,
                updated_at=conv.updated_at,
                members=[UserBrief.model_validate(u) for u in members],
                last_message=MessageOut.model_validate(last_msg) if last_msg else None,
                unread_count=unread,
            )
        )
    return result


@router.post("/conversations", response_model=ConversationOut, status_code=201)
async def create_conversation(
    data: ConversationCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    member_ids = set(data.member_ids)
    member_ids.add(current_user.id)

    # For direct (non-group) chats, reuse existing conversation if present
    if not data.is_group and len(member_ids) == 2:
        other_id = (member_ids - {current_user.id}).pop()
        existing = (
            db.query(Conversation)
            .join(ConversationMember)
            .filter(Conversation.is_group == False)
            .group_by(Conversation.id)
            .having(
                # simplistic check — improve with subquery in production
                True
            )
            .all()
        )
        for c in existing:
            ids = {m.user_id for m in c.members}
            if ids == member_ids:
                return ConversationOut(
                    id=c.id,
                    title=c.title,
                    is_group=c.is_group,
                    created_at=c.created_at,
                    updated_at=c.updated_at,
                    members=[UserBrief.model_validate(m.user) for m in c.members],
                    unread_count=0,
                )

    conv = Conversation(title=data.title, is_group=data.is_group)
    db.add(conv)
    db.flush()
    for uid in member_ids:
        db.add(ConversationMember(conversation_id=conv.id, user_id=uid))
    db.commit()
    db.refresh(conv)
    members = db.query(User).filter(User.id.in_(member_ids)).all()
    return ConversationOut(
        id=conv.id,
        title=conv.title,
        is_group=conv.is_group,
        created_at=conv.created_at,
        updated_at=conv.updated_at,
        members=[UserBrief.model_validate(u) for u in members],
        unread_count=0,
    )


@router.get("/conversations/{conv_id}/messages", response_model=List[MessageOut])
async def get_messages(
    conv_id: int,
    limit: int = 50,
    before_id: int | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    membership = (
        db.query(ConversationMember)
        .filter(
            ConversationMember.conversation_id == conv_id,
            ConversationMember.user_id == current_user.id,
        )
        .first()
    )
    if not membership:
        raise HTTPException(status_code=403, detail="Not a member of this conversation")

    query = (
        db.query(Message)
        .options(joinedload(Message.sender))
        .filter(Message.conversation_id == conv_id)
    )
    if before_id:
        query = query.filter(Message.id < before_id)
    messages = query.order_by(Message.created_at.desc()).limit(limit).all()
    messages.reverse()

    # Mark as read
    membership.last_read_at = datetime.utcnow()
    db.commit()
    return messages


@router.post("/conversations/{conv_id}/messages", response_model=MessageOut, status_code=201)
async def send_message(
    conv_id: int,
    data: MessageCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    membership = (
        db.query(ConversationMember)
        .filter(
            ConversationMember.conversation_id == conv_id,
            ConversationMember.user_id == current_user.id,
        )
        .first()
    )
    if not membership:
        raise HTTPException(status_code=403, detail="Not a member of this conversation")

    msg = Message(conversation_id=conv_id, sender_id=current_user.id, body=data.body)
    db.add(msg)
    conv = db.query(Conversation).filter(Conversation.id == conv_id).first()
    if conv:
        conv.updated_at = datetime.utcnow()
    membership.last_read_at = datetime.utcnow()
    db.commit()
    db.refresh(msg)

    # Notify other members via WebSocket
    other_members = (
        db.query(ConversationMember)
        .filter(
            ConversationMember.conversation_id == conv_id,
            ConversationMember.user_id != current_user.id,
        )
        .all()
    )
    payload = {
        "type": "new_message",
        "conversation_id": conv_id,
        "message": MessageOut.model_validate(msg).model_dump(mode="json"),
    }
    for m in other_members:
        await manager.send_to_user(m.user_id, payload)

    return msg


@router.websocket("/ws")
async def chat_websocket(websocket: WebSocket, token: str = ""):
    try:
        token_data = decode_token(token)
        user_id = token_data.user_id
    except Exception:
        await websocket.close(code=4001)
        return

    await manager.connect(user_id, websocket)
    try:
        while True:
            # Keep-alive / client pings
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        manager.disconnect(user_id, websocket)