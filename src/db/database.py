from sqlalchemy import Column, Integer, String, Text, DateTime, JSON, Boolean
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy import create_engine
import os
from datetime import datetime

Base = declarative_base()

class User(Base):
    __tablename__ = 'users'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    password_hash = Column(String(128), nullable=False)
    role = Column(String(20), default='vip') # admin, editor, vip
    valid_until = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=datetime.now)

class MatchPrediction(Base):
    __tablename__ = 'match_predictions'

    id = Column(Integer, primary_key=True, autoincrement=True)
    fixture_id = Column(String(50), index=True)  # 移除unique约束，允许多个时间段记录
    match_num = Column(String(50))
    league = Column(String(100))
    home_team = Column(String(100))
    away_team = Column(String(100))
    match_time = Column(DateTime)
    
    # 时间段标识：pre_24h, pre_12h, final
    prediction_period = Column(String(20), default='pre_24h')
    
    # 原始数据 JSON 存储
    raw_data = Column(JSON)
    
    # AI 预测结果
    prediction_text = Column(Text)
    
    # 半全场(平胜/平负) 专项预测结果
    htft_prediction_text = Column(Text, nullable=True)
    
    # 结构化预测结果 (后续可扩展，用于回测)
    predicted_result = Column(String(50), nullable=True) # 胜/平/负
    confidence = Column(Integer, nullable=True) # 1-5星
    
    # 实际赛果
    actual_result = Column(String(50), nullable=True)
    actual_score = Column(String(50), nullable=True)
    actual_bqc = Column(String(20), nullable=True) # 半全场赛果 (e.g. 1-3)
    is_correct = Column(Boolean, nullable=True)
    
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

class BasketballPrediction(Base):
    __tablename__ = 'basketball_predictions'

    id = Column(Integer, primary_key=True, autoincrement=True)
    fixture_id = Column(String(50), index=True)
    match_num = Column(String(50))
    league = Column(String(100))
    home_team = Column(String(100))
    away_team = Column(String(100))
    match_time = Column(DateTime)
    
    # 原始数据 JSON 存储
    raw_data = Column(JSON)
    
    # AI 预测结果
    prediction_text = Column(Text)
    
    # 实际赛果
    actual_score = Column(String(50), nullable=True)
    
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

class SfcPrediction(Base):
    __tablename__ = 'sfc_predictions'

    id = Column(Integer, primary_key=True, autoincrement=True)
    issue_num = Column(String(50), index=True) # 期号
    fixture_id = Column(String(50))
    match_num = Column(String(50)) # 例如 胜负彩_1
    league = Column(String(100))
    home_team = Column(String(100))
    away_team = Column(String(100))
    match_time = Column(DateTime)
    
    # 原始数据 JSON 存储
    raw_data = Column(JSON)
    
    # AI 预测结果
    prediction_text = Column(Text)
    
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

class DailyParlays(Base):
    """用于存储每日生成的串子单方案"""
    __tablename__ = 'daily_parlays'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    # 保存方案生成的日期 (格式: YYYY-MM-DD)
    target_date = Column(String(20), index=True)
    # 最新的方案内容
    current_parlay = Column(Text)
    # 上一次的方案内容（用于对比）
    previous_parlay = Column(Text, nullable=True)
    # AI对两次方案的对比分析结果
    comparison_text = Column(Text, nullable=True)
    
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

class DailyReview(Base):
    """用于存储每日复盘结果"""
    __tablename__ = 'daily_reviews'

    id = Column(Integer, primary_key=True, autoincrement=True)
    target_date = Column(String(20), index=True, unique=True)
    review_content = Column(Text) # LLM的复盘总结
    htft_review_content = Column(Text, nullable=True) # 半全场专项复盘总结
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

class Database:
    def __init__(self, db_url=None):
        if db_url is None:
            # 动态计算绝对路径，确保无论从哪个目录启动，都能找到正确的 data/football.db
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            db_path = os.path.join(base_dir, "data", "football.db")
            db_url = f"sqlite:///{db_path}"
            
        # 确保目录存在
        if db_url.startswith("sqlite:///"):
            db_path = db_url.replace("sqlite:///", "")
            os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
            
        self.engine = create_engine(db_url)
        Base.metadata.create_all(self.engine)
        Session = sessionmaker(bind=self.engine)
        self.session = Session()

    def save_prediction(self, match_data, period='pre_24h'):
        """保存或更新预测结果，支持时间段标识"""
        try:
            fixture_id = match_data.get("fixture_id")
            if not fixture_id:
                return False
                
            # 尝试查找是否存在相同fixture_id和period的记录
            record = self.session.query(MatchPrediction).filter_by(
                fixture_id=fixture_id, 
                prediction_period=period
            ).first()
            
            match_time_str = match_data.get("match_time")
            try:
                # 尝试解析时间
                match_time = datetime.strptime(match_time_str, "%Y-%m-%d %H:%M")
            except:
                match_time = None

            if not record:
                # 新建记录
                record = MatchPrediction(
                    fixture_id=fixture_id,
                    match_num=match_data.get("match_num"),
                    league=match_data.get("league"),
                    home_team=match_data.get("home_team"),
                    away_team=match_data.get("away_team"),
                    match_time=match_time,
                    prediction_period=period,
                    raw_data=match_data,
                    prediction_text=match_data.get("llm_prediction", ""),
                    htft_prediction_text=match_data.get("htft_prediction", "")
                )
                self.session.add(record)
            else:
                # 更新记录
                record.raw_data = match_data
                if match_data.get("llm_prediction"):
                    record.prediction_text = match_data.get("llm_prediction")
                if match_data.get("htft_prediction"):
                    record.htft_prediction_text = match_data.get("htft_prediction")
                    
            self.session.commit()
            return True
        except Exception as e:
            self.session.rollback()
            print(f"数据库保存失败: {e}")
            return False
            
    def close(self):
        self.session.close()

    def get_user(self, username):
        return self.session.query(User).filter_by(username=username).first()

    def get_prediction(self, match_num):
        """根据比赛编号获取最新的全场预测记录"""
        return self.session.query(MatchPrediction).filter(
            MatchPrediction.match_num.like(f"%{match_num}%")
        ).order_by(MatchPrediction.created_at.desc()).first()

    def get_prediction_by_period(self, fixture_id, period):
        """根据时间段获取预测结果"""
        return self.session.query(MatchPrediction).filter_by(
            fixture_id=fixture_id, 
            prediction_period=period
        ).first()
    
    def get_all_predictions_by_fixture(self, fixture_id):
        """获取某场比赛的所有时间段预测结果"""
        return self.session.query(MatchPrediction).filter_by(
            fixture_id=fixture_id
        ).order_by(MatchPrediction.created_at.desc()).all()

    def save_bball_prediction(self, match_data):
        """保存篮球预测结果"""
        try:
            fixture_id = match_data.get("fixture_id")
            if not fixture_id:
                return False
                
            record = self.session.query(BasketballPrediction).filter_by(
                fixture_id=fixture_id
            ).first()
            
            match_time_str = match_data.get("match_time")
            try:
                match_time = datetime.strptime(match_time_str, "%Y-%m-%d %H:%M")
            except:
                match_time = None

            if not record:
                record = BasketballPrediction(
                    fixture_id=fixture_id,
                    match_num=match_data.get("match_num"),
                    league=match_data.get("league"),
                    home_team=match_data.get("home_team"),
                    away_team=match_data.get("away_team"),
                    match_time=match_time,
                    raw_data=match_data,
                    prediction_text=match_data.get("llm_prediction", "")
                )
                self.session.add(record)
            else:
                record.raw_data = match_data
                if match_data.get("llm_prediction"):
                    record.prediction_text = match_data.get("llm_prediction")
                    
            self.session.commit()
            return True
        except Exception as e:
            self.session.rollback()
            print(f"篮球数据库保存失败: {e}")
            return False

    def get_bball_prediction_by_fixture(self, fixture_id):
        """获取某场篮球比赛的预测结果"""
        return self.session.query(BasketballPrediction).filter_by(
            fixture_id=fixture_id
        ).first()

    def save_sfc_prediction(self, match_data):
        """保存胜负彩预测结果"""
        try:
            issue_num = match_data.get("issue_num")
            match_num = match_data.get("match_num")
            
            if not issue_num or not match_num:
                return False
                
            record = self.session.query(SfcPrediction).filter_by(
                issue_num=issue_num,
                match_num=match_num
            ).first()
            
            match_time_str = match_data.get("match_time")
            try:
                match_time = datetime.strptime(match_time_str, "%Y-%m-%d %H:%M")
            except:
                match_time = None

            if not record:
                record = SfcPrediction(
                    issue_num=issue_num,
                    fixture_id=match_data.get("fixture_id", ""),
                    match_num=match_num,
                    league=match_data.get("league"),
                    home_team=match_data.get("home_team"),
                    away_team=match_data.get("away_team"),
                    match_time=match_time,
                    raw_data=match_data,
                    prediction_text=match_data.get("llm_prediction", "")
                )
                self.session.add(record)
            else:
                record.raw_data = match_data
                if match_data.get("llm_prediction"):
                    record.prediction_text = match_data.get("llm_prediction")
                    
            self.session.commit()
            return True
        except Exception as e:
            self.session.rollback()
            print(f"胜负彩数据库保存失败: {e}")
            return False

    def get_sfc_prediction(self, issue_num, match_num):
        """获取某场胜负彩比赛的预测结果"""
        return self.session.query(SfcPrediction).filter_by(
            issue_num=issue_num,
            match_num=match_num
        ).first()

    def get_parlays_by_date(self, target_date):
        """获取指定日期的串关方案"""
        return self.session.query(DailyParlays).filter_by(target_date=target_date).first()

    def save_parlays(self, target_date, current_parlay, previous_parlay=None, comparison_text=None):
        """保存当天的串关方案"""
        try:
            record = self.get_parlays_by_date(target_date)
            if not record:
                record = DailyParlays(
                    target_date=target_date,
                    current_parlay=current_parlay,
                    previous_parlay=previous_parlay,
                    comparison_text=comparison_text
                )
                self.session.add(record)
            else:
                record.current_parlay = current_parlay
                if previous_parlay is not None:
                    record.previous_parlay = previous_parlay
                if comparison_text is not None:
                    record.comparison_text = comparison_text
            self.session.commit()
            return True
        except Exception as e:
            self.session.rollback()
            print(f"保存串关方案失败: {e}")
            return False

    def get_predictions_by_date(self, target_date):
        """获取指定日期的所有预测（日周期窗口: 目标日 12:00 ~ 次日 12:00）"""
        from datetime import datetime, timedelta
        
        try:
            start_date = datetime.strptime(target_date, "%Y-%m-%d")
            window_start = start_date.replace(hour=12, minute=0, second=0)
            window_end = (start_date + timedelta(days=1)).replace(hour=12, minute=0, second=0)
            
            records = self.session.query(MatchPrediction).filter(
                MatchPrediction.match_time >= window_start,
                MatchPrediction.match_time < window_end
            ).all()
        except Exception as e:
            print(f"查询日期失败: {e}")
            records = []
            
        # 相同fixture_id可能有多个period，repredicted(历史重新预测)最高优先，其次final/pre_12h/pre_24h
        result_map = {}
        priority = {'repredicted': 5, 'final': 3, 'pre_12h': 2, 'pre_24h': 1}
        for r in records:
            fid = r.fixture_id
            if fid not in result_map:
                result_map[fid] = r
            else:
                if priority.get(r.prediction_period, 0) > priority.get(result_map[fid].prediction_period, 0):
                    result_map[fid] = r
        return list(result_map.values())

    def update_actual_result(self, fixture_id, score, bqc_result=None):
        """更新比赛实际赛果"""
        try:
            records = self.session.query(MatchPrediction).filter_by(fixture_id=fixture_id).all()
            for record in records:
                record.actual_score = score
                if bqc_result:
                    record.actual_bqc = bqc_result
                # 此处可以增加计算 actual_result 的逻辑
            self.session.commit()
            return True
        except Exception as e:
            self.session.rollback()
            print(f"更新赛果失败: {e}")
            return False

    def get_daily_review(self, target_date):
        """获取某日的复盘记录"""
        return self.session.query(DailyReview).filter_by(target_date=target_date).first()

    def save_daily_review(self, target_date, review_content, htft_review_content=None):
        """保存某日的复盘记录"""
        try:
            record = self.get_daily_review(target_date)
            if not record:
                record = DailyReview(
                    target_date=target_date,
                    review_content=review_content,
                    htft_review_content=htft_review_content
                )
                self.session.add(record)
            else:
                if review_content is not None:
                    record.review_content = review_content
                if htft_review_content is not None:
                    record.htft_review_content = htft_review_content
            self.session.commit()
            return True
        except Exception as e:
            self.session.rollback()
            print(f"保存复盘失败: {e}")
            return False

if __name__ == "__main__":
    db = Database()
    print("数据库初始化成功！")
