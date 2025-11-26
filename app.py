from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional
from datetime import datetime

import numpy as np
import pandas as pd
import requests
from flask import Flask, jsonify, render_template, request, redirect, url_for, flash
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from sklearn.impute import KNNImputer
from tensorflow.keras.models import load_model
from werkzeug.security import generate_password_hash, check_password_hash

# Import models
from models import db, User, Prediction, ContactMessage
from sqlalchemy import desc

BASE_DIR = Path(__file__).resolve().parent
DATASET_PATH = BASE_DIR / "apcrop_dataset_realistic.csv"
MODEL_PATH = BASE_DIR / "croprecommender_mlp.h5"
META_PATH = BASE_DIR / "croprecommender_mlp.npz"

EXCLUDE_COLUMNS = [
    "Year",
    "Suitable_Crops",
    "Fertilizer_Plan",
    "Irrigation_Plan",
    "Market_Price_Index",
    "Previous_Crop",
]

DISTRICT_COORDINATES: Dict[str, Dict[str, float]] = {
    "Alluri Sitharama Raju": {"lat": 17.6, "lon": 81.9},
    "Anakapalli": {"lat": 17.6868, "lon": 83.0033},
    "Anantapuram": {"lat": 14.6819, "lon": 77.6006},
    "Annamayya": {"lat": 13.95, "lon": 78.5},
    "Bapatla": {"lat": 15.8889, "lon": 80.4593},
    "Chittoor": {"lat": 13.2172, "lon": 79.1003},
    "East Godavari": {"lat": 17.321, "lon": 82.04},
    "Eluru": {"lat": 16.7107, "lon": 81.0952},
    "Guntur": {"lat": 16.3067, "lon": 80.4365},
    "Kakinada": {"lat": 16.9891, "lon": 82.2475},
    "Konaseema": {"lat": 16.65, "lon": 82.0},
    "Krishna": {"lat": 16.57, "lon": 80.36},
    "Kurnool": {"lat": 15.8281, "lon": 78.0373},
    "NTR": {"lat": 16.5062, "lon": 80.648},
    "Nandyal": {"lat": 15.4888, "lon": 78.4836},
    "Palnadu": {"lat": 16.1167, "lon": 80.1667},
    "Parvathipuram Manyam": {"lat": 18.8, "lon": 83.433},
    "Prakasam": {"lat": 15.5, "lon": 79.5},
    "Sri Potti Sriramulu Nellore": {"lat": 14.4426, "lon": 79.9865},
    "Sri Sathya Sai": {"lat": 14.4, "lon": 77.8},
    "Srikakulam": {"lat": 18.2989, "lon": 83.8938},
    "Tirupati": {"lat": 13.6288, "lon": 79.4192},
    "Visakhapatnam": {"lat": 17.6868, "lon": 83.2185},
    "Vizianagaram": {"lat": 18.113, "lon": 83.3956},
    "West Godavari": {"lat": 16.7107, "lon": 81.0972},
    "YSR Kadapa": {"lat": 14.4673, "lon": 78.8242},
}

GOVERNMENT_SCHEMES = [
    {
        "title": "YSR Rythu Bharosa",
        "description": "Financial assistance of ₹13,500 per annum for small and marginal farmers in Andhra Pradesh.",
        "link": "https://ysrrythubharosa.ap.gov.in/",
    },
    {
        "title": "PM-KISAN",
        "description": "Central scheme providing ₹6,000 per year in three installments to eligible farmer families.",
        "link": "https://pmkisan.gov.in/",
    },
    {
        "title": "Pradhan Mantri Fasal Bima Yojana",
        "description": "Crop insurance that protects farmers against losses due to unforeseen events.",
        "link": "https://pmfby.gov.in/",
    },
    {
        "title": "Micro Irrigation Fund",
        "description": "Subsidized loans for drip and sprinkler systems to encourage water-use efficiency.",
        "link": "https://nmsa.dac.gov.in/MIF.aspx",
    },
]

CHATBOT_KNOWLEDGE = [
    {
        "question": "How do I raise soil pH?",
        "keywords": ["ph", "soil", "acidic", "lime"],
        "answer": "Apply agricultural lime (2-3 t/ha) and incorporate organic matter like compost to buffer acidity. Re-test soil after one season.",
    },
    {
        "question": "How can I reduce irrigation costs?",
        "keywords": ["irrigation", "water", "drip", "sprinkler"],
        "answer": "Shift to drip/sprinkler systems, irrigate during cooler hours, and use mulching to reduce evaporation.",
    },
    {
        "question": "Which fertilizer is best for paddy?",
        "keywords": ["paddy", "fertilizer", "npk"],
        "answer": "A balanced plan is 100-120 kg N, 40-50 kg P2O5, 40-50 kg K2O per hectare split across basal, tillering, and panicle initiation stages.",
    },
    {
        "question": "How do I access government schemes?",
        "keywords": ["scheme", "government", "subsidy"],
        "answer": "Visit the Rythu Bharosa Kendram or apply online via the respective portals with your Aadhaar and land records.",
    },
]

def safe_mode(series: pd.Series) -> Optional[Any]:
    mode_values = series.mode()
    return mode_values.iloc[0] if not mode_values.empty else None

def safe_mean(series: pd.Series) -> Optional[float]:
    if series.empty:
        return None
    value = float(series.mean())
    if pd.isna(value):
        return None
    return round(value, 2)

class DistrictDataService:
    def __init__(self, dataset: pd.DataFrame) -> None:
        self.dataset = dataset.copy()
        self.district_summary = self._build_district_summary()
        self.seasonal_summary = self._build_seasonal_summary()
        self.mandal_lookup = self._build_mandal_lookup()

    def _build_district_summary(self) -> Dict[str, Dict[str, Any]]:
        summary: Dict[str, Dict[str, Any]] = {}
        for district, group in self.dataset.groupby("District"):
            summary[district] = self._summarize_group(group)
        return summary

    def _build_seasonal_summary(self) -> Dict[str, Dict[str, Any]]:
        seasonal: Dict[str, Dict[str, Any]] = {}
        for (district, season), group in self.dataset.groupby(["District", "Season"]):
            seasonal_key = f"{district}::{season}"
            seasonal[seasonal_key] = self._summarize_group(group)
        return seasonal

    def _build_mandal_lookup(self) -> Dict[str, List[str]]:
        lookup: Dict[str, List[str]] = {}
        for district, group in self.dataset.groupby("District"):
            lookup[district] = sorted(group["Mandal"].dropna().unique())
        return lookup

    def _summarize_group(self, group: pd.DataFrame) -> Dict[str, Any]:
        summary = {
            "district": group["District"].iloc[0],
            "mandal": safe_mode(group["Mandal"]),
            "season": safe_mode(group["Season"]),
            "soil_type": safe_mode(group["Soil_Type"]),
            "water_source": safe_mode(group["Water_Source"]),
            "secondary_crop": safe_mode(group["Secondary_Crop"]),
            "primary_crop": safe_mode(group["Primary_Crop"]),
            "soil_ph": safe_mean(group["Soil_pH"]),
            "organic_carbon": safe_mean(group["Organic_Carbon_pct"]),
            "soil_n": safe_mean(group["Soil_N_kg_ha"]),
            "soil_p": safe_mean(group["Soil_P_kg_ha"]),
            "soil_k": safe_mean(group["Soil_K_kg_ha"]),
            "rainfall": safe_mean(group["Seasonal_Rainfall_mm"]),
            "humidity": safe_mean(group["Avg_Humidity_pct"]),
            "temperature": safe_mean(group["Avg_Temp_C"]),
        }
        return summary

    def get_districts(self) -> List[str]:
        return sorted(self.district_summary.keys())

    def get_district_data(self, district: str) -> Dict[str, Any]:
        data = self.district_summary.get(district)
        if not data:
            raise ValueError(f"District '{district}' is not in the dataset.")
        return {**data, "mandals": self.mandal_lookup.get(district, [])}

    def get_auto_defaults(self, district: str, season: Optional[str]) -> Dict[str, Any]:
        if district not in self.district_summary:
            raise ValueError(f"District '{district}' is not in the dataset.")
        if season:
            seasonal_key = f"{district}::{season}"
            if seasonal_key in self.seasonal_summary:
                return self.seasonal_summary[seasonal_key]
        return self.district_summary[district]

    def build_model_payload(
        self,
        district: str,
        season: Optional[str],
        raw_payload: Dict[str, Any],
        mode: str,
    ) -> Dict[str, Any]:
        summary = self.get_auto_defaults(district, season)
        mandal = raw_payload.get("mandal") or summary.get("mandal")
        soil_type = raw_payload.get("soil_type") or summary.get("soil_type")
        water_source = raw_payload.get("water_source") or summary.get("water_source")
        season_value = season or raw_payload.get("season") or summary.get("season")

        def value_or_default(key: str, override_key: str) -> Optional[float]:
            if mode == "manual":
                override_value = raw_payload.get(override_key)
                if override_value in ("", None):
                    return summary.get(key)
                try:
                    return float(override_value)
                except (TypeError, ValueError):
                    return summary.get(key)
            return summary.get(key)

        return {
            "District": district,
            "Mandal": mandal,
            "Season": season_value,
            "Soil_Type": soil_type,
            "Soil_pH": value_or_default("soil_ph", "soil_ph"),
            "Organic_Carbon_pct": value_or_default("organic_carbon", "organic_carbon"),
            "Soil_N_kg_ha": value_or_default("soil_n", "soil_n"),
            "Soil_P_kg_ha": value_or_default("soil_p", "soil_p"),
            "Soil_K_kg_ha": value_or_default("soil_k", "soil_k"),
            "Avg_Temp_C": summary.get("temperature"),
            "Seasonal_Rainfall_mm": summary.get("rainfall"),
            "Avg_Humidity_pct": summary.get("humidity"),
            "Water_Source": water_source,
            "Secondary_Crop": summary.get("secondary_crop"),
            "Primary_Crop": summary.get("primary_crop"),
        }

    def fetch_guidance(self, district: str, crop: str) -> Dict[str, Any]:
        filtered = self.dataset[
            (self.dataset["District"] == district) & (self.dataset["Primary_Crop"] == crop)
        ]
        if filtered.empty:
            filtered = self.dataset[self.dataset["Primary_Crop"] == crop]
        if filtered.empty:
            return {}
        row = filtered.iloc[0]
        fertilizer_plan = self._safe_json(row.get("Fertilizer_Plan"))
        irrigation_plan = self._safe_json(row.get("Irrigation_Plan"))
        market_index = row.get("Market_Price_Index")
        return {
            "fertilizer_plan": fertilizer_plan,
            "irrigation_plan": irrigation_plan,
            "market_index": market_index,
        }

    @staticmethod
    def _safe_json(value: Any) -> Optional[Dict[str, Any]]:
        if not isinstance(value, str):
            return None
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return None

class WeatherService:
    def __init__(self, coordinates: Dict[str, Dict[str, float]]) -> None:
        self.coordinates = coordinates

    def get_weather(self, district: str) -> Optional[Dict[str, Any]]:
        coords = self.coordinates.get(district)
        if not coords:
            return None
        params = {
            "latitude": coords["lat"],
            "longitude": coords["lon"],
            "current_weather": True,
            "hourly": "temperature_2m,relativehumidity_2m,precipitation",
        }
        try:
            response = requests.get(
                "https://api.open-meteo.com/v1/forecast",
                params=params,
                timeout=8,
            )
            response.raise_for_status()
            payload = response.json()
            current = payload.get("current_weather", {})
            hourly_payload = payload.get("hourly", {})
            hourly_records: List[Dict[str, Any]] = []
            times = hourly_payload.get("time", []) or []
            temps = hourly_payload.get("temperature_2m", []) or []
            humidity = hourly_payload.get("relativehumidity_2m", []) or []
            precipitation = hourly_payload.get("precipitation", []) or []
            for idx, time_value in enumerate(times[:12]):
                hourly_records.append(
                    {
                        "time": time_value,
                        "temperature": self._safe_index(temps, idx),
                        "humidity": self._safe_index(humidity, idx),
                        "precipitation": self._safe_index(precipitation, idx),
                    }
                )
            return {
                "current": {
                    "temperature": current.get("temperature"),
                    "windspeed": current.get("windspeed"),
                    "weathercode": current.get("weathercode"),
                    "time": current.get("time"),
                },
                "hourly": hourly_records,
            }
        except requests.RequestException:
            return None

    @staticmethod
    def _safe_index(values: List[Any], index: int) -> Optional[Any]:
        try:
            return values[index]
        except (IndexError, TypeError):
            return None

class SchemeService:
    def __init__(self, schemes: List[Dict[str, Any]]) -> None:
        self.schemes = schemes

    def list_schemes(self) -> List[Dict[str, Any]]:
        return self.schemes

class ChatbotService:
    def __init__(self, knowledge_base: List[Dict[str, Any]]) -> None:
        self.knowledge_base = knowledge_base

    def answer(self, message: str) -> str:
        text = (message or "").lower()
        if not text.strip():
            return "Please enter a question about crops, soil, irrigation, or schemes."
        best_match = ""
        best_score = 0
        for entry in self.knowledge_base:
            score = sum(1 for keyword in entry["keywords"] if keyword in text)
            if score > best_score:
                best_score = score
                best_match = entry["answer"]
        if best_score == 0:
            return (
                "I do not have an exact answer. Please reach out to your local "
                "Krishi Vigyan Kendra for expert advice."
            )
        return best_match

class CropRecommendationEngine:
    def __init__(self, dataset: pd.DataFrame) -> None:
        self.model = load_model(MODEL_PATH)
        meta = np.load(META_PATH, allow_pickle=True)
        self.feature_cols = list(meta["feature_cols"])
        self.classes = list(meta["classes"])

        self.dataset = dataset.drop(columns=EXCLUDE_COLUMNS, errors="ignore").copy()
        if "Primary_Crop" not in self.dataset.columns:
            raise ValueError("Primary_Crop column missing from dataset.")

        self.placeholder_primary = safe_mode(self.dataset["Primary_Crop"]) or "Paddy"
        self.input_columns = list(self.dataset.columns)

        self.numeric_cols = self._identify_numeric_columns()
        self.categorical_cols = self._identify_categorical_columns()

        self.imputer = None
        if self.numeric_cols:
            self.imputer = KNNImputer(n_neighbors=5)
            numeric_df = self.dataset[self.numeric_cols]
            self.imputer.fit(numeric_df)

        self.cat_dummy_columns = self._build_categorical_template()

    def _identify_numeric_columns(self) -> List[str]:
        feature_df = self.dataset.drop(columns=["Primary_Crop"])
        numeric_cols = feature_df.select_dtypes(include=np.number).columns.tolist()
        return [col for col in numeric_cols if not feature_df[col].isnull().all()]

    def _identify_categorical_columns(self) -> List[str]:
        feature_df = self.dataset.drop(columns=["Primary_Crop"])
        categorical_cols = feature_df.select_dtypes(exclude=np.number).columns.tolist()
        return categorical_cols

    def _build_categorical_template(self) -> List[str]:
        if not self.categorical_cols:
            return []
        cat_df = (
            self.dataset[self.categorical_cols]
            .copy()
            .fillna("Unknown")
        )
        encoded = pd.get_dummies(cat_df, columns=self.categorical_cols, drop_first=True)
        return list(encoded.columns)

    def _build_row(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        row: Dict[str, Any] = {}
        for column in self.input_columns:
            if column == "Primary_Crop":
                row[column] = payload.get(column) or self.placeholder_primary
            else:
                row[column] = payload.get(column)
        return row

    def _transform_numeric(self, X: pd.DataFrame) -> pd.DataFrame:
        if not self.numeric_cols or self.imputer is None:
            return pd.DataFrame(index=X.index)
        numeric_df = X[self.numeric_cols].apply(pd.to_numeric, errors="coerce")
        transformed = self.imputer.transform(numeric_df)
        return pd.DataFrame(transformed, columns=self.numeric_cols)

    def _transform_categorical(self, X: pd.DataFrame) -> pd.DataFrame:
        if not self.categorical_cols:
            return pd.DataFrame(index=X.index)
        cat_df = X[self.categorical_cols].copy().fillna("Unknown")
        encoded = pd.get_dummies(cat_df, columns=self.categorical_cols, drop_first=True)
        encoded = encoded.reindex(columns=self.cat_dummy_columns, fill_value=0)
        return encoded

    def predict(self, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        row = self._build_row(payload)
        sample_df = pd.DataFrame([row])
        features = sample_df.drop(columns=["Primary_Crop"], errors="ignore")

        numeric_part = self._transform_numeric(features)
        categorical_part = self._transform_categorical(features)

        combined = pd.concat([numeric_part, categorical_part], axis=1)
        combined = combined.reindex(columns=self.feature_cols, fill_value=0)

        predictions = self.model.predict(combined.values, verbose=0)[0]
        top_indices = predictions.argsort()[::-1][:3]
        return [
            {"crop": self.classes[idx], "score": round(float(predictions[idx]), 4)}
            for idx in top_indices
        ]

app = Flask(__name__)

# Configuration
database_url = os.environ.get('DATABASE_URL')

# Fallback to SQLite if DATABASE_URL is not set or empty
if not database_url:
    database_url = 'sqlite:///agrointelligence.db'
    print("⚠️  DATABASE_URL not set. Using local SQLite database.")
else:
    # Fix for Render PostgreSQL URL (postgres:// -> postgresql://)
    if database_url.startswith('postgres://'):
        database_url = database_url.replace('postgres://', 'postgresql://', 1)

app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

print(f"✅ Database Configured: {app.config['SQLALCHEMY_DATABASE_URI'].split('://')[0]}://...")

# Initialize extensions
db.init_app(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

DATASET = pd.read_csv(DATASET_PATH)
district_service = DistrictDataService(DATASET)
recommendation_engine = CropRecommendationEngine(DATASET)
scheme_service = SchemeService(GOVERNMENT_SCHEMES)
chatbot_service = ChatbotService(CHATBOT_KNOWLEDGE)
weather_service = WeatherService(DISTRICT_COORDINATES)

@app.route("/")
def home() -> str:
    return render_template("landing.html")

@app.route("/login", methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
        
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        remember = True if request.form.get('remember') else False
        
        user = User.query.filter_by(email=email).first()
        
        if user and user.check_password(password):
            login_user(user, remember=remember)
            return redirect(url_for('dashboard'))
        else:
            flash('Please check your login details and try again.', 'error')
            
    return render_template('login.html')

@app.route("/signup", methods=['GET', 'POST'])
def signup():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
        
    if request.method == 'POST':
        email = request.form.get('email')
        username = request.form.get('username')
        password = request.form.get('password')
        full_name = request.form.get('full_name')
        phone = request.form.get('phone')
        
        user = User.query.filter_by(email=email).first()
        if user:
            flash('Email address already exists', 'error')
            return redirect(url_for('signup'))
            
        new_user = User(
            email=email,
            username=username,
            full_name=full_name,
            phone=phone
        )
        new_user.set_password(password)
        
        db.session.add(new_user)
        db.session.commit()
        
        flash('Account created successfully! Please log in.', 'success')
        return redirect(url_for('login'))
        
    return render_template('signup.html')

@app.route("/verify_email/<token>")
def verify_email(token):
    user = User.query.filter_by(verification_token=token).first()
    if user:
        user.email_verified = True
        user.verification_token = None
        db.session.commit()
        flash('Email verified successfully!', 'success')
    else:
        flash('Invalid or expired verification link.', 'error')
    return redirect(url_for('login'))

@app.route("/profile")
@login_required
def profile():
    # Calculate stats
    prediction_count = Prediction.query.filter_by(user_id=current_user.id).count()
    days_member = (datetime.utcnow() - current_user.created_at).days
    return render_template('profile.html', prediction_count=prediction_count, days_member=days_member)

@app.route("/update_profile", methods=['POST'])
@login_required
def update_profile():
    # Update personal details
    current_user.full_name = request.form.get('full_name')
    current_user.phone = request.form.get('phone')
    
    # Update farm details
    current_user.district = request.form.get('district')
    try:
        current_user.farm_size = float(request.form.get('farm_size')) if request.form.get('farm_size') else None
    except ValueError:
        pass
    current_user.primary_crops = request.form.get('primary_crops')
    
    # Password change
    new_password = request.form.get('new_password')
    if new_password:
        current_password = request.form.get('current_password')
        if current_user.check_password(current_password):
            if request.form.get('confirm_new_password') == new_password:
                current_user.set_password(new_password)
                flash('Password updated successfully', 'success')
            else:
                flash('New passwords do not match', 'error')
        else:
            flash('Incorrect current password', 'error')
            
    db.session.commit()
    flash('Profile updated successfully', 'success')
    return redirect(url_for('profile'))

@app.route("/history")
@login_required
def history():
    predictions = Prediction.query.filter_by(user_id=current_user.id).order_by(desc(Prediction.created_at)).all()
    return render_template('history.html', predictions=predictions)

@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for('home'))

@app.route("/dashboard", methods=['GET'])
def dashboard() -> str:
    return render_template("index.html", user=current_user)

@app.route("/about")
def about_page() -> str:
    return render_template("about.html")

@app.route("/weather")
def weather_page() -> str:
    return render_template("weather.html")

@app.route("/schemes-center")
def schemes_page() -> str:
    return render_template("schemes.html")

@app.route("/contact", methods=['GET', 'POST'])
def contact_page() -> str:
    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        message = request.form.get('message')
        
        msg = ContactMessage(name=name, email=email, message=message)
        db.session.add(msg)
        db.session.commit()
        flash('Message sent successfully!', 'success')
        return redirect(url_for('contact_page'))
        
    return render_template("contact.html")

@app.route("/faq")
def faq_page() -> str:
    return render_template("faq.html")

@app.route("/privacy")
def privacy_page() -> str:
    return render_template("privacy.html")

@app.route("/terms")
def terms_page() -> str:
    return render_template("terms.html")

@app.route("/get_district_names")
def get_district_names() -> Any:
    return jsonify(district_service.get_districts())

@app.route("/get_district_data/<district_name>")
def get_district_data(district_name: str) -> Any:
    try:
        return jsonify(district_service.get_district_data(district_name))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 404

@app.route("/auto_defaults")
def auto_defaults() -> Any:
    district = request.args.get("district")
    season = request.args.get("season")
    if not district:
        return jsonify({"error": "district is required"}), 400
    try:
        data = district_service.get_auto_defaults(district, season)
        return jsonify(data)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 404

@app.route("/api/weather/<district>")
def weather(district: str) -> Any:
    data = weather_service.get_weather(district)
    if not data:
        return jsonify({"error": "Weather data unavailable"}), 404
    return jsonify(data)

@app.route("/schemes")
def schemes() -> Any:
    return jsonify(scheme_service.list_schemes())

@app.route("/chat", methods=["POST"])
def chat() -> Any:
    payload = request.get_json() or {}
    message = payload.get("message", "")
    response = chatbot_service.answer(message)
    return jsonify({"response": response})

@app.route("/predict", methods=["GET", "POST"])
def predict() -> Any:
    # If GET request, redirect to dashboard with message
    if request.method == "GET":
        mode = request.args.get("mode", "manual")
        flash(f'Please use the {mode.title()} Mode form below to get predictions.', 'info')
        return redirect(url_for('dashboard'))
    
    # POST request - process prediction
    payload = request.get_json()
    if not payload:
        return jsonify({"error": "Invalid input payload"}), 400

    district = payload.get("district")
    if not district:
        return jsonify({"error": "Please select a district"}), 400

    season = payload.get("season")
    mode = payload.get("mode", "manual").lower()
    if mode not in {"manual", "auto"}:
        return jsonify({"error": "Mode must be 'manual' or 'auto'"}), 400

    try:
        model_payload = district_service.build_model_payload(
            district=district,
            season=season,
            raw_payload=payload,
            mode=mode,
        )
        recommendations = recommendation_engine.predict(model_payload)
        top_crop = recommendations[0]["crop"]
        guidance = district_service.fetch_guidance(district, top_crop)
        location_snapshot = district_service.get_auto_defaults(district, season)
        weather_snapshot = weather_service.get_weather(district)

        # Save prediction to database
        try:
            prediction = Prediction(
                user_id=current_user.id,
                district=district,
                mandal=model_payload.get("Mandal"),
                season=model_payload.get("Season"),
                soil_type=model_payload.get("Soil_Type"),
                water_source=model_payload.get("Water_Source"),
                mode=mode,
                top_crop=recommendations[0]["crop"],
                top_crop_score=recommendations[0]["score"],
                second_crop=recommendations[1]["crop"] if len(recommendations) > 1 else None,
                second_crop_score=recommendations[1]["score"] if len(recommendations) > 1 else None,
                third_crop=recommendations[2]["crop"] if len(recommendations) > 2 else None,
                third_crop_score=recommendations[2]["score"] if len(recommendations) > 2 else None,
            )
            db.session.add(prediction)
            db.session.commit()
        except Exception as e:
            print(f"Error saving prediction: {e}")

        response_payload = {
            "mode": mode,
            "recommendations": recommendations,
            "location_details": {
                "district": district,
                "mandal": model_payload.get("Mandal"),
                "season": model_payload.get("Season"),
                "soil_type": model_payload.get("Soil_Type"),
                "rainfall": location_snapshot.get("rainfall"),
                "humidity": location_snapshot.get("humidity"),
            },
            "guidance": guidance,
            "weather": weather_snapshot,
            "auto_defaults": location_snapshot,
        }
        return jsonify(response_payload)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception:
        return jsonify({"error": "Unable to generate recommendations at the moment."}), 500


@app.route("/login/google")
def login_google():
    flash("Google Login is not configured in this demo.", "info")
    return redirect(url_for("login"))

@app.route("/login/facebook")
def login_facebook():
    flash("Facebook Login is not configured in this demo.", "info")
    return redirect(url_for("login"))

if __name__ == "__main__":

    with app.app_context():
        db.create_all()
    app.run(debug=True, port=5000)
