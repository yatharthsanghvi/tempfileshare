from flask import Flask, request, send_file, session, render_template, abort, url_for, redirect
from werkzeug.utils import secure_filename
import os
import uuid
import threading
import time
import json
import base64
import zipfile

app = Flask(__name__)
app.secret_key = os.urandom(24)  # Set a secret key for sessions

# Directory to store up loaded files
UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16 MB max file size

# Ensure the upload folder exists
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

def delete_file(file_path, metadata_path, delay_minutes):
    time.sleep(delay_minutes * 60)  # Convert minutes to seconds
    if os.path.exists(file_path):
        try:
            os.remove(file_path)
            os.remove(metadata_path)
            app.logger.info(f"Deleted file: {file_path}")
        except Exception as e:
            app.logger.error(f"Error deleting file {file_path}: {str(e)}")

@app.route('/')
def home():
    return render_template('home.html')

@app.route('/upload', methods=['GET', 'POST'])
def upload_file():
    if request.method == 'POST':
        if 'file' not in request.files:
            return render_template('error.html', error_message='No file part')
        
        files = request.files.getlist('file')  # Get all files as a list

        if len(files) == 0 or all(f.filename == '' for f in files):
            return render_template('error.html', error_message='No selected files')

        # Generate a unique identifier for the zip file
        zip_file_id = str(uuid.uuid4())[:8]  # Shortened UUID to 8 characters
        zip_filename = f"{zip_file_id}.zip"
        zip_path = os.path.join(app.config['UPLOAD_FOLDER'], zip_filename)

        try:
            with zipfile.ZipFile(zip_path, 'w') as zipf:
                for file in files:
                    if file and file.filename != '':
                        filename = secure_filename(file.filename)
                        file_id = str(uuid.uuid4())[:8]  # Shortened UUID for internal file tracking
                        file_path = os.path.join(app.config['UPLOAD_FOLDER'], f"{file_id}_{filename}")
                        file.save(file_path)

                        # Add file to zip
                        zipf.write(file_path, filename)

                        # Remove the individual file after adding to zip
                        os.remove(file_path)

            try:
                delete_after = int(request.form.get('delete_after', 60))
                delete_after = min(max(delete_after, 1), 60)  # Ensure between 1 and 60 minutes
            except ValueError:
                delete_after = 60

            # Save metadata for the zip file
            metadata = {
                'filename': zip_filename,
                'delete_after': delete_after,
                'upload_time': time.time()
            }
            metadata_path = os.path.join(app.config['UPLOAD_FOLDER'], f"{zip_file_id}_metadata.json")
            with open(metadata_path, 'w') as f:
                json.dump(metadata, f)

            # Start deletion thread for the zip file and its metadata
            threading.Thread(target=delete_file, args=(zip_path, metadata_path, delete_after)).start()

            filename_without_extension = os.path.splitext(zip_file_id)[0]

            download_url = url_for('download_page', file_id=zip_file_id, _external=True)
            return render_template('upload_result.html', download_url=download_url, delete_after=delete_after, filename=zip_filename,filename_without_extension=filename_without_extension)

        except Exception as e:
            app.logger.error(f"Error creating zip file: {str(e)}")
            return render_template('error.html', error_message="Error creating zip file")

    return render_template('upload.html')

@app.route('/download', methods=['GET', 'POST'])
def download_page():
    if request.method == 'POST':
        file_id = request.form.get('token')
        if not file_id:
            return render_template('error.html', error_message="Token is required")

        metadata_path = os.path.join(app.config['UPLOAD_FOLDER'], f"{file_id}_metadata.json")
        if os.path.exists(metadata_path):
            with open(metadata_path, 'r') as f:
                metadata = json.load(f)
            
            filename = metadata['filename']
            delete_after = metadata['delete_after']
            upload_time = metadata['upload_time']

            # Calculate remaining time
            elapsed_time = time.time() - upload_time
            remaining_minutes = max(0, int(delete_after - elapsed_time / 60))

            return render_template('download.html', file_id=file_id, filename=filename, delete_after=remaining_minutes)
        else:
            return render_template('error.html', error_message="Invalid token or file does not exist")

    return render_template('token_input.html')  # Render the token input form

@app.route('/download/<file_id>/start')
def initiate_download(file_id):
    zip_filename = f"{file_id}.zip"
    zip_path = os.path.join(app.config['UPLOAD_FOLDER'], zip_filename)
    
    if os.path.exists(zip_path):
        try:
            # Send the zip file as an attachment
            return send_file(zip_path, as_attachment=True, download_name=zip_filename)
        except Exception as e:
            app.logger.error(f"Error sending file: {str(e)}")
            abort(500)
    else:
        abort(404)

@app.errorhandler(404)
def not_found_error(error):
    return render_template('error.html', error_message="File not found"), 404

@app.errorhandler(500)
def internal_error(error):
    return render_template('error.html', error_message="Internal server error"), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
