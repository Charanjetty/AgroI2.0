# User Authentication and Database Models
# This file will be imported by app.py

from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import secrets

db = SQLAlchemy()

class User(UserMixin, db.Model):
    """User model for authentication"""
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    full_name = db.Column(db.String(100))
    phone = db.Column(db.String(15))
    district = db.Column(db.String(50))
    
    # Email verification
    email_verified = db.Column(db.Boolean, default=False)
    verification_token = db.Column(db.String(100), unique=True)
    
    # Profile information
    profile_image = db.Column(db.String(200), default='default_avatar.png')
    farm_size = db.Column(db.Float)  # in acres
    primary_crops = db.Column(db.String(200))
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime)
    
    # Relationships
    predictions = db.relationship('Prediction', backref='user', lazy=True, cascade='all, delete-orphan')
    
    def set_password(self, password):
        """Hash and set password"""
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        """Check if password matches"""
        return check_password_hash(self.password_hash, password)
    
    def generate_verification_token(self):
        """Generate email verification token"""
        self.verification_token = secrets.token_urlsafe(32)
        return self.verification_token
    
    def __repr__(self):
        return f'<User {self.username}>'


class Prediction(db.Model):
    """Model to store user predictions"""
    __tablename__ = 'predictions'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    
    # Input parameters
    district = db.Column(db.String(50), nullable=False)
    mandal = db.Column(db.String(50))
    season = db.Column(db.String(20))
    soil_type = db.Column(db.String(30))
    water_source = db.Column(db.String(30))
    mode = db.Column(db.String(10))  # manual or auto
    
    # Soil parameters (for manual mode)
    soil_ph = db.Column(db.Float)
    organic_carbon = db.Column(db.Float)
    soil_n = db.Column(db.Float)
    soil_p = db.Column(db.Float)
    soil_k = db.Column(db.Float)
    
    # Results
    top_crop = db.Column(db.String(50))
    top_crop_score = db.Column(db.Float)
    second_crop = db.Column(db.String(50))
    second_crop_score = db.Column(db.Float)
    third_crop = db.Column(db.String(50))
    third_crop_score = db.Column(db.Float)
    
    # Timestamp
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<Prediction {self.id} - {self.top_crop}>'


class ContactMessage(db.Model):
    """Model to store contact form submissions"""
    __tablename__ = 'contact_messages'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(15))
    subject = db.Column(db.String(200))
    message = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(20), default='new')  # new, read, replied
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<ContactMessage {self.id} from {self.name}>'
