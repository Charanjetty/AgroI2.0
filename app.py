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
# from tensorflow.keras.models import load_model  <-- REMOVED top-level import
from werkzeug.security import generate_password_hash, check_password_hash

# Import models
from models import db, User, Prediction, ContactMessage
from sqlalchemy import desc

BASE_DIR = Path(__file__).resolve().parent
DATASET_PATH = BASE_DIR / "apcrop_dataset_realistic.csv"
MODEL_PATH = BASE_DIR / "croprecommender_mlp.h5"
META_PATH = BASE_DIR / "croprecommender_mlp.npz"

# ... (rest of constants) ...

class CropRecommendationEngine:
    def __init__(self, dataset: pd.DataFrame) -> None:
        # Lazy load model components
        self.model = None
        self.dataset = dataset.copy()
        # Pre-load dataset metadata (lightweight)
        if "Primary_Crop" not in self.dataset.columns:
            # Fallback if dataset is not loaded correctly
            self.placeholder_primary = "Paddy"
        else:
            self.placeholder_primary = safe_mode(self.dataset["Primary_Crop"]) or "Paddy"
            
        # We will initialize the rest in _ensure_loaded()

    def _ensure_loaded(self):
        """Loads the heavy model and TensorFlow only when needed."""
        if self.model is not None:
            return

        print("⏳ Loading TensorFlow and Model...")
        # Local import to save memory on startup
        from tensorflow.keras.models import load_model
        
        self.model = load_model(MODEL_PATH)
        meta = np.load(META_PATH, allow_pickle=True)
        self.feature_cols = list(meta["feature_cols"])
        self.classes = list(meta["classes"])

        self.dataset = self.dataset.drop(columns=EXCLUDE_COLUMNS, errors="ignore")
        self.input_columns = list(self.dataset.columns)

        self.numeric_cols = self._identify_numeric_columns()
        self.categorical_cols = self._identify_categorical_columns()

        self.imputer = None
        if self.numeric_cols:
            self.imputer = KNNImputer(n_neighbors=5)
            numeric_df = self.dataset[self.numeric_cols]
            self.imputer.fit(numeric_df)

        self.cat_dummy_columns = self._build_categorical_template()
        print("✅ Model Loaded Successfully")

    def _identify_numeric_columns(self) -> List[str]:
        feature_df = self.dataset.drop(columns=["Primary_Crop"], errors='ignore')
        numeric_cols = feature_df.select_dtypes(include=np.number).columns.tolist()
        return [col for col in numeric_cols if not feature_df[col].isnull().all()]

    def _identify_categorical_columns(self) -> List[str]:
        feature_df = self.dataset.drop(columns=["Primary_Crop"], errors='ignore')
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
        self._ensure_loaded()  # <--- Load model here!
        
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

# ... (rest of app setup) ...



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

# Initialize Services
DATASET = pd.read_csv(DATASET_PATH)
district_service = DistrictDataService(DATASET)
recommendation_engine = CropRecommendationEngine(DATASET)
scheme_service = SchemeService(GOVERNMENT_SCHEMES)
chatbot_service = ChatbotService(CHATBOT_KNOWLEDGE)
weather_service = WeatherService(DISTRICT_COORDINATES)

if __name__ == "__main__":

    with app.app_context():
        db.create_all()
    app.run(debug=True, port=5000)
