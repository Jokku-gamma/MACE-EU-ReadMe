import os
import json
import base64
import uuid
from flask import Flask, request, jsonify
from flask_cors import CORS
from github import Github
from datetime import datetime
from werkzeug.utils import secure_filename
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)
CORS(app)

# --- CONFIGURATION FROM ENV ---
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
REPO_NAME = os.environ.get("GITHUB_REPO_NAME")
WEBSITE_URL = os.environ.get("WEBSITE_URL")

# Defaults (can be overridden by env if needed)
JSON_PATH = os.environ.get("JSON_PATH")
UPLOAD_FOLDER = os.environ.get("UPLOAD_FOLDER")

# Validation: Ensure critical vars exist
if not GITHUB_TOKEN or not REPO_NAME or not WEBSITE_URL:
    raise ValueError("Missing critical environment variables! Check your .env file.")

# Allowed extensions
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'pdf'}

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# --- HEALTH CHECK ROUTE ---
@app.route('/', methods=['GET'])
def health_check():
    """
    Simple route to check if server is reachable.
    """
    return jsonify({
        "status": "online",
        "message": "MACE EU Content Manager API is running...",
        "repo": REPO_NAME
    }), 200

@app.route('/add-post', methods=['POST'])
def add_post():
    try:
        # 1. Connect to GitHub
        g = Github(GITHUB_TOKEN)
        repo = g.get_repo(REPO_NAME)

        # 2. Handle Text Data (Form Data)
        title = request.form.get('title')
        author = request.form.get('author')
        content = request.form.get('content')
        post_type = request.form.get('type') # 'article', 'pdf', 'image', 'video'
        media_url = request.form.get('mediaUrl', '') # For YouTube links

        if not title or not author:
            return jsonify({"error": "Title and Author are required"}), 400

        # 3. Handle File Upload (Image/PDF)
        uploaded_file_url = ""
        
        if 'file' in request.files:
            file = request.files['file']
            if file and allowed_file(file.filename):
                # Generate unique filename to avoid overwrites
                ext = file.filename.rsplit('.', 1)[1].lower()
                unique_filename = f"{uuid.uuid4().hex}.{ext}"
                repo_path = f"{UPLOAD_FOLDER}{unique_filename}"
                
                # Read file bytes
                file_content = file.read()
                
                # Push file to GitHub Repo
                try:
                    repo.create_file(
                        path=repo_path,
                        message=f"Upload media: {title}",
                        content=file_content,
                        branch="main" 
                    )
                    # Construct the URL where this file will be hosted
                    uploaded_file_url = f"{WEBSITE_URL}{repo_path}"
                except Exception as e:
                    return jsonify({"error": f"File upload failed: {str(e)}"}), 500

        # 4. Determine Final Media URL
        # If we uploaded a file, use that URL. Otherwise use the YouTube link provided.
        final_media_url = uploaded_file_url if uploaded_file_url else media_url
        
        # Auto-set media type based on upload
        final_media_type = 'none'
        if post_type == 'video': final_media_type = 'youtube'
        elif post_type == 'pdf': final_media_type = 'pdf'
        elif post_type == 'image' or uploaded_file_url: final_media_type = 'image'

        # 5. Prepare New Post Object
        new_post = {
            "id": str(uuid.uuid4()),
            "title": title,
            "author": author,
            "date": datetime.now().strftime("%b %d, %Y"),
            "type": post_type,
            "banner": "https://images.unsplash.com/photo-1504052434569-70ad5836ab65", 
            "content": content,
            "mediaType": final_media_type,
            "mediaUrl": final_media_url
        }

        # 6. Update posts.json in Repo
        try:
            file_content = repo.get_contents(JSON_PATH)
            existing_data = json.loads(base64.b64decode(file_content.content).decode('utf-8'))
        except:
            existing_data = []
            file_content = None

        existing_data.insert(0, new_post)
        updated_json = json.dumps(existing_data, indent=2)

        commit_msg = f"New post: {title}"
        if file_content:
            repo.update_file(JSON_PATH, commit_msg, updated_json, file_content.sha)
        else:
            repo.create_file(JSON_PATH, commit_msg, updated_json)

        return jsonify({
            "message": "Post and media uploaded successfully!", 
            "url": final_media_url
        }), 200

    except Exception as e:
        print(f"Error: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    # Run on 0.0.0.0 to make it accessible to your Flutter app on the network
    app.run(debug=True, host='0.0.0.0', port=5000)