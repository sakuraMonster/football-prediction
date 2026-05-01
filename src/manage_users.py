import sys
import os
import hashlib
from datetime import datetime, timedelta

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.db.database import Database, User

def hash_password(password):
    return hashlib.sha256(password.encode('utf-8')).hexdigest()

def create_or_update_user(username, password, role="vip", days_valid=30):
    db = Database()
    
    # 查找用户是否存在
    user = db.session.query(User).filter_by(username=username).first()
    
    valid_until = datetime.now() + timedelta(days=days_valid)
    hashed_pw = hash_password(password)
    
    if user:
        user.password_hash = hashed_pw
        user.role = role
        user.valid_until = valid_until
        print(f"✅ 已更新用户: {username} | 角色: {role} | 有效期至: {valid_until.strftime('%Y-%m-%d %H:%M')}")
    else:
        new_user = User(
            username=username,
            password_hash=hashed_pw,
            role=role,
            valid_until=valid_until
        )
        db.session.add(new_user)
        print(f"🎉 已创建新用户: {username} | 角色: {role} | 有效期至: {valid_until.strftime('%Y-%m-%d %H:%M')}")
        
    db.session.commit()
    db.close()

if __name__ == "__main__":
    print("=== 用户管理工具 ===")
    # 默认创建两个测试账号
    create_or_update_user("admin", "admin123", role="admin", days_valid=365)
    create_or_update_user("vip_user", "123456", role="vip", days_valid=30)
    create_or_update_user("expired_user", "123456", role="vip", days_valid=-1) # 过期测试账号
