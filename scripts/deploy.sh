#!/bin/bash
# ══════════════════════════════════════════════════════════════════════════════
# TaskFlow VM Deployment Script
# ══════════════════════════════════════════════════════════════════════════════
# This script is designed to be run on a fresh Ubuntu 22.04+ VM.
# It installs Docker, clones the repository, and starts the full stack.

set -e

REPO_URL="https://github.com/sridhar8910/Taskflow.git"
DEST_DIR="/opt/taskflow"

echo "🚀 Starting TaskFlow Deployment..."

# 1. Install Docker and Docker Compose if not present
if ! command -v docker &> /dev/null; then
    echo "📦 Installing Docker..."
    curl -fsSL https://get.docker.com -o get-docker.sh
    sudo sh get-docker.sh
    sudo usermod -aG docker $USER
    rm get-docker.sh
fi

# 2. Clone the repository
if [ ! -d "$DEST_DIR" ]; then
    echo "📥 Cloning repository..."
    sudo git clone $REPO_URL $DEST_DIR
    sudo chown -R $USER:$USER $DEST_DIR
else
    echo "🔄 Updating existing repository..."
    cd $DEST_DIR
    git pull origin main
fi

cd $DEST_DIR

# 3. Setup Environment Variables
if [ ! -f ".env" ]; then
    echo "⚙️ Setting up .env file..."
    cp .env.example .env
    
    # Generate a secure secret key for production
    SECRET_KEY=$(openssl rand -hex 32)
    sed -i "s/change-me-to-a-long-random-string-before-deploying/$SECRET_KEY/g" .env
    
    # Set environment to production
    sed -i "s/APP_ENV=development/APP_ENV=production/g" .env
fi

# 4. Start the stack
echo "🐳 Starting Docker containers..."
docker compose build
docker compose up -d

# 5. Run database migrations
echo "🗄️ Running database migrations..."
# Wait a few seconds for DB to be ready
sleep 5
docker compose exec -T api alembic upgrade head

echo "✅ Deployment complete! The API is running on port 8000."
