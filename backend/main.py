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
JSON_PATH = os.environ.get("JSON_PATH", "gospel.json")
UPLOAD_FOLDER = os.environ.get("UPLOAD_FOLDER", "gospel-uploads/")

# FIX: Ensure UPLOAD_FOLDER ends with a slash to prevent "gospel-uploadsfilename.png" errors
if not UPLOAD_FOLDER.endswith('/'):
    UPLOAD_FOLDER += '/'

# FIX: Ensure WEBSITE_URL ends with a slash if needed for path concatenation
if WEBSITE_URL and not WEBSITE_URL.endswith('/'):
    WEBSITE_URL += '/'

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

# --- ADD POST ROUTE ---
@app.route('/add-post', methods=['POST'])
def add_post():
    try:
        # Debugging: Print what the server receives
        print("--- NEW UPLOAD REQUEST ---")
        # print("Form Data:", request.form) # Uncomment if needed
        # print("Files:", request.files)    # Uncomment if needed

        # 1. Connect to GitHub
        g = Github(GITHUB_TOKEN)
        repo = g.get_repo(REPO_NAME)

        # 2. Get Form Data
        title = request.form.get('title')
        author = request.form.get('author')
        content = request.form.get('content')
        post_type = request.form.get('type') # 'article', 'image', 'video' (youtube), 'pdf'
        media_url_input = request.form.get('mediaUrl', '') # The link (YouTube/PDF)

        if not title or not author:
            return jsonify({"error": "Title and Author are required"}), 400

        # --- 3. HANDLE BANNER IMAGE (Required) ---
        banner_full_url = ""
        
        if 'file' in request.files:
            file = request.files['file']
            if file and allowed_file(file.filename):
                ext = file.filename.rsplit('.', 1)[1].lower()
                unique_filename = f"{uuid.uuid4().hex}.{ext}"
                
                # Correct Path Construction (now safe due to the fix at top of file)
                repo_path = f"{UPLOAD_FOLDER}{unique_filename}"
                
                print(f"Uploading banner to: {repo_path}") 

                # Upload Banner to GitHub
                repo.create_file(
                    path=repo_path,
                    message=f"Upload banner: {title}",
                    content=file.read(),
                    branch="main" 
                )
                
                # Construct the full URL
                banner_full_url = f"{WEBSITE_URL}{repo_path}"
        
        # Fallback if no banner sent
        if not banner_full_url:
             print("Warning: No file uploaded, using fallback banner.")
             banner_full_url = "https://images.unsplash.com/photo-1504052434569-70ad5836ab65" 

        # --- 4. DETERMINE FINAL MEDIA CONFIGURATION ---
        final_media_url = ""
        final_media_type = "none"

        if post_type == 'image':
            # For Image posts, the Banner IS the main visual
            final_media_url = banner_full_url
            final_media_type = 'image'
            
        elif post_type == 'video' or post_type == 'youtube':
            # For Video, Banner is cover, Input URL is the YouTube link
            final_media_url = media_url_input
            final_media_type = 'youtube'
            
        elif post_type == 'pdf':
             # For PDF, Banner is cover, Input URL is the PDF link
             final_media_url = media_url_input
             final_media_type = 'pdf'
             
        elif post_type == 'article':
            # Article has no extra media, just text and banner
            final_media_url = ""
            final_media_type = "none"

        # --- 5. CREATE POST OBJECT ---
        new_post = {
            "id": str(uuid.uuid4()),
            "title": title,
            "author": author,
            "date": datetime.now().strftime("%b %d, %Y"),
            "type": post_type,
            "banner": banner_full_url,      # Banner is the uploaded image
            "content": content,
            "mediaType": final_media_type, 
            "mediaUrl": final_media_url     # Content is the Link
        }

        # --- 6. UPDATE JSON ---
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
            "message": "Success", 
            "id": new_post['id'], 
            "url": final_media_url,
            "banner_url": banner_full_url
        }), 200

    except Exception as e:
        print(f"Server Error: {e}")
        return jsonify({"error": str(e)}), 500

# --- DELETE POST ROUTE ---
@app.route('/delete-post', methods=['POST'])
def delete_post():
    try:
        # 1. Get the ID to delete
        data = request.json
        post_id = data.get('id')
        
        if not post_id:
            return jsonify({"error": "Post ID is required"}), 400

        # 2. Connect to GitHub
        g = Github(GITHUB_TOKEN)
        repo = g.get_repo(REPO_NAME)
        
        # 3. Fetch gospel.json
        file_content = repo.get_contents(JSON_PATH)
        existing_data = json.loads(base64.b64decode(file_content.content).decode('utf-8'))
        
        # 4. Filter out the post with the matching ID
        # We keep everything that does NOT match the ID
        new_data = [post for post in existing_data if post.get('id') != post_id]
        
        # Check if anything was actually removed
        if len(new_data) == len(existing_data):
            return jsonify({"error": "Post not found"}), 404

        # 5. Commit changes
        updated_json = json.dumps(new_data, indent=2)
        repo.update_file(JSON_PATH, f"Delete post: {post_id}", updated_json, file_content.sha)
        
        return jsonify({"message": "Post deleted successfully"}), 200

    except Exception as e:
        print(f"Error: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    # Run on 0.0.0.0 to make it accessible to your Flutter app on the network
    app.run(debug=True, host='0.0.0.0', port=5000)