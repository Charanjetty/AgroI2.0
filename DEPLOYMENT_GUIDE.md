# 🚀 Deployment Guide for AgroIntelligence

## Deploying to Render

### Prerequisites
- GitHub account
- Render account (sign up at https://render.com)
- Your code pushed to a GitHub repository

---

## Step-by-Step Deployment Instructions

### 1. **Push Your Code to GitHub**

```bash
# Initialize git if not already done
git init

# Add all files
git add .

# Commit your changes
git commit -m "Prepare for Render deployment"

# Add your GitHub repository as remote
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO.git

# Push to GitHub
git push -u origin main
```

---

### 2. **Create a New Web Service on Render**

1. Go to https://dashboard.render.com
2. Click **"New +"** → **"Web Service"**
3. Connect your GitHub repository
4. Select your **AgroIntelligence** repository

---

### 3. **Configure Your Web Service**

Use these **EXACT** settings:

| Setting | Value |
|---------|-------|
| **Name** | `agrointelligence` (or your preferred name) |
| **Region** | Choose closest to your users |
| **Branch** | `main` |
| **Root Directory** | *(leave empty)* |
| **Runtime** | `Python 3` |
| **Build Command** | `pip install -r requirements.txt` |
| **Start Command** | `gunicorn app:app` |

---

### 4. **Choose Instance Type**

**For Testing/Hobby Projects:**
- Select **Free** ($0/month)
- ⚠️ App will sleep after 15 min of inactivity
- ⚠️ 512 MB RAM, 0.1 CPU

**For Production:**
- Select **Starter** ($7/month) or higher
- ✅ No sleeping
- ✅ Better performance
- ✅ SSH access

---

### 5. **Add Environment Variables**

Click **"Advanced"** and add these environment variables:

| Variable Name | Value | Notes |
|--------------|-------|-------|
| `PYTHON_VERSION` | `3.11.0` | Python runtime version |
| `SECRET_KEY` | *(click "Generate")* | Auto-generate a secure key |

**Note:** `DATABASE_URL` will be added automatically when you create the database.

---

### 6. **Create a PostgreSQL Database** (Optional but Recommended)

1. In Render Dashboard, click **"New +"** → **"PostgreSQL"**
2. Configure:
   - **Name**: `agrointelligence-db`
   - **Database**: `agrointelligence`
   - **User**: `agrointelligence_user`
   - **Region**: Same as your web service
   - **Instance Type**: **Free** (for testing)

3. Click **"Create Database"**

4. Once created, go back to your **Web Service** settings
5. Add environment variable:
   - **Key**: `DATABASE_URL`
   - **Value**: Copy from your PostgreSQL database's "Internal Database URL"

---

### 7. **Deploy!**

1. Click **"Create Web Service"**
2. Render will:
   - Clone your repository
   - Install dependencies
   - Start your application
3. Wait 5-10 minutes for the first deployment

---

### 8. **Access Your Application**

Once deployed, your app will be available at:
```
https://agrointelligence.onrender.com
```
*(or your chosen name)*

---

## Important Notes

### ⚠️ Large Files Warning
Your application includes:
- `apcrop_dataset_realistic.csv` (9.8 MB)
- `croprecommender_mlp.h5` (1.1 MB)

These are within Render's limits, but deployment may take longer.

### 🔄 Auto-Deploy
Render automatically redeploys when you push to GitHub:
```bash
git add .
git commit -m "Update application"
git push
```

### 📊 Free Tier Limitations
- **Web Service**: Sleeps after 15 min inactivity
- **Database**: 90 days expiration, 1 GB storage
- **Bandwidth**: 100 GB/month

### 🆙 Upgrading
To upgrade instance type:
1. Go to your service settings
2. Click **"Instance Type"**
3. Select **Starter** ($7/month) or higher
4. Click **"Save Changes"**

---

## Troubleshooting

### Build Fails
- Check build logs in Render dashboard
- Ensure all dependencies are in `requirements.txt`
- Verify Python version compatibility

### Application Crashes
- Check application logs in Render dashboard
- Ensure `DATABASE_URL` is set correctly
- Verify all environment variables are configured

### Database Connection Issues
- Ensure PostgreSQL database is running
- Check `DATABASE_URL` format: `postgresql://user:password@host/database`
- Verify database is in the same region as web service

---

## Alternative: Deploy to Vercel

If you prefer Vercel (requires more setup):

1. Install Vercel CLI:
   ```bash
   npm install -g vercel
   ```

2. Create `vercel.json`:
   ```json
   {
     "version": 2,
     "builds": [
       {
         "src": "app.py",
         "use": "@vercel/python"
       }
     ],
     "routes": [
       {
         "src": "/(.*)",
         "dest": "app.py"
       }
     ]
   }
   ```

3. Deploy:
   ```bash
   vercel
   ```

**Note:** Vercel requires external database (Supabase, PlanetScale, etc.)

---

## Support

For issues:
- Check Render documentation: https://render.com/docs
- Review application logs in Render dashboard
- Ensure all files are committed to GitHub

---

**Good luck with your deployment! 🎉**
