"""Initial accounts, rooms, invitations and messages."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import DATETIME
revision = '0001'
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    op.create_table('users', sa.Column('id', sa.Uuid(), primary_key=True), sa.Column('username', sa.String(32), nullable=False, unique=True), sa.Column('display_name', sa.String(50), nullable=False), sa.Column('password_hash', sa.String(255), nullable=False), sa.Column('created_at', sa.DateTime(timezone=True).with_variant(DATETIME(fsp=6), 'mysql'), nullable=False), mysql_engine='InnoDB', mysql_charset='utf8mb4')
    op.create_table('rooms', sa.Column('id', sa.Uuid(), primary_key=True), sa.Column('name', sa.String(80), nullable=False), sa.Column('destination', sa.String(100), nullable=False), sa.Column('start_date', sa.Date(), nullable=False), sa.Column('end_date', sa.Date(), nullable=False), sa.Column('owner_id', sa.Uuid(), sa.ForeignKey('users.id'), nullable=False), sa.Column('version', sa.Integer(), nullable=False), sa.Column('status', sa.String(24), nullable=False), sa.Column('created_at', sa.DateTime(timezone=True).with_variant(DATETIME(fsp=6), 'mysql'), nullable=False), sa.CheckConstraint('end_date >= start_date', name='room_dates_order'), mysql_engine='InnoDB', mysql_charset='utf8mb4')
    op.create_table('room_members', sa.Column('id', sa.Uuid(), primary_key=True), sa.Column('room_id', sa.Uuid(), sa.ForeignKey('rooms.id'), nullable=False), sa.Column('user_id', sa.Uuid(), sa.ForeignKey('users.id'), nullable=False), sa.Column('display_name', sa.String(50), nullable=False), sa.Column('role', sa.String(16), nullable=False), sa.Column('status', sa.String(16), nullable=False), sa.Column('joined_at', sa.DateTime(timezone=True).with_variant(DATETIME(fsp=6), 'mysql'), nullable=False), sa.UniqueConstraint('room_id', 'user_id', name='uq_room_user'), mysql_engine='InnoDB', mysql_charset='utf8mb4')
    op.create_index('ix_room_members_room_id', 'room_members', ['room_id'])
    op.create_table('invitations', sa.Column('id', sa.Uuid(), primary_key=True), sa.Column('room_id', sa.Uuid(), sa.ForeignKey('rooms.id'), nullable=False), sa.Column('code_hash', sa.String(64), unique=True, nullable=False), sa.Column('expires_at', sa.DateTime(timezone=True).with_variant(DATETIME(fsp=6), 'mysql'), nullable=False), mysql_engine='InnoDB', mysql_charset='utf8mb4')
    op.create_index('ix_invitations_room_id', 'invitations', ['room_id'])
    op.create_table('messages', sa.Column('sequence', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), primary_key=True, autoincrement=True), sa.Column('id', sa.Uuid(), nullable=False, unique=True), sa.Column('room_id', sa.Uuid(), sa.ForeignKey('rooms.id'), nullable=False), sa.Column('author_member_id', sa.Uuid(), sa.ForeignKey('room_members.id'), nullable=False), sa.Column('content', sa.Text(), nullable=False), sa.Column('created_at', sa.DateTime(timezone=True).with_variant(DATETIME(fsp=6), 'mysql'), nullable=False), mysql_engine='InnoDB', mysql_charset='utf8mb4')
    op.create_index('ix_messages_room_id', 'messages', ['room_id'])

def downgrade():
    op.drop_table('messages')
    op.drop_table('invitations')
    op.drop_table('room_members')
    op.drop_table('rooms')
    op.drop_table('users')
