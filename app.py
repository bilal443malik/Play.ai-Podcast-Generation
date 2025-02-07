from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
import requests
import os
from fpdf import FPDF
import cloudinary
import cloudinary.uploader
import urllib.parse
import uvicorn

app = FastAPI()

import cloudinary.api
# Configure Cloudinary
cloudinary.config(
    cloud_name="",  # Replace with your Cloudinary cloud name
    api_key="",  # Replace with your Cloudinary API key
    api_secret=""  # Replace with your Cloudinary API secret
)

###########################################
# Utility Functions
###########################################

def get_all_blog_with_pagination():
    """
    Retrieves all blog entries from a paginated Strapi API endpoint.
    
    Returns:
        list: A list containing all blog entries aggregated from all pages.
    """
    base_url = "<Getting Some Blogs from a DB>"
    all_entries = []
    page = 1
    
    try:
        # Initial request to get pagination metadata
        response = requests.get(f"{base_url}?pagination[page]={page}&pagination[pageSize]=100")
        response.raise_for_status()
        data = response.json()
        
        # Extract pagination details
        pagination = data.get('meta', {}).get('pagination', {})
        total_pages = pagination.get('pageCount', 1)
        all_entries.extend(data.get('data', []))
        
        # Fetch remaining pages if they exist
        while page < total_pages:
            page += 1
            response = requests.get(f"{base_url}?pagination[page]={page}&pagination[pageSize]=100")
            response.raise_for_status()
            page_data = response.json()
            all_entries.extend(page_data.get('data', []))
            
    except requests.exceptions.RequestException as e:
        print(f"Error fetching data: {e}")
        return []
    
    return all_entries

def upload_pdf(file_path):
    """
    Uploads a PDF file to Cloudinary and returns the PDF URL.
    
    Args:
        file_path (str): Local path of the PDF file.
        
    Returns:
        str or None: The URL of the uploaded PDF or None if upload fails.
    """
    folder_name = "PodCast_pdfs"
    try:
        response = cloudinary.uploader.upload(
            file_path,
            folder=folder_name,
            resource_type="raw"
        )
        pdf_url = response.get("url")
        print(f"PDF URL: {pdf_url}")
        return pdf_url
    except Exception as e:
        print(f"Error uploading PDF: {e}")
        return None

def generate_podcast(pdf_url):
    """
    Calls the PlayNote API to generate a podcast from the given PDF URL.
    
    Args:
        pdf_url (str): The URL of the PDF file (uploaded to Cloudinary).
        
    Returns:
        dict: A dictionary containing either the audio URL (if completed)
              or a message about the generation status.
    """
    play_note_api_url = "https://api.play.ai/api/v1/playnotes"
    
    # Retrieve PlayNote credentials from environment variables
    api_key = "ak-"
    user_id = ""
    print("API Key:", api_key)
    print("User ID:", user_id)

    headers = {
        'AUTHORIZATION': api_key,
        'X-USER-ID': user_id,
        'accept': 'application/json'
    }
    
    # Configure the request parameters
    files = {
        'sourceFileUrl': (None, pdf_url),
        'synthesisStyle': (None, 'podcast'),
        'voice1': (None, 's3://voice-cloning-zero-shot/baf1ef41-36b6-428c-9bdf-50ba54682bd8/original/manifest.json'),
        'voice1Name': (None, 'Angelo'),
        'voice2': (None, 's3://voice-cloning-zero-shot/e040bd1b-f190-4bdb-83f0-75ef85b18f84/original/manifest.json'),
        'voice2Name': (None, 'Deedee'),
    }
    
    # POST to PlayNote API to start podcast generation
    response = requests.post(play_note_api_url, headers=headers, files=files)
    print("###########")
    print(response.status_code)
    if response.status_code == 201:
        play_note_id = response.json().get('id')
        print(f"Generated PlayNote ID: {play_note_id}")
        
        # Double encode the PlayNote ID to build the status URL
        double_encoded_id = urllib.parse.quote(play_note_id, safe='')
        status_url = f"{play_note_api_url}/{double_encoded_id}"
        status_response = requests.get(status_url, headers=headers)
        if status_response.status_code == 200:
            status_data = status_response.json()
            if status_data.get('status') == 'completed':
                audio_url = status_data.get('audioUrl')
                return {
                    "status": "completed", "audioUrl": audio_url,
                    "Generated PlayNote ID:": {play_note_id}
                    }
            elif status_data.get('status') == 'generating':
                return {
                    "status": "generating", "message": "Please wait while your PlayNote is being generated. Try again later!",
                    "Generating PlayNote with ID:": {play_note_id}
                    }
            else:
                return {"status": "error", "message": "PlayNote Creation was not successful, please try again."}
        else:
            return {"status": "error", "message": f"Error checking status: {status_response.text}"}
    else:
        return {"status": "error", "message": f"Failed to generate PlayNote: {response}"}

###########################################
# Request Model
###########################################

class CategoryRequest(BaseModel):
    category: str

###########################################
# API Endpoints
###########################################

@app.get("/categories")
async def get_categories():
    """
    Returns the list of six static categories.
    """
    Endpoint_url = "https://customerhub-server-m8avm.ondigitalocean.app/api"
    response = requests.get(f"{Endpoint_url}/blog-categories")
    categories = [category["Name"] for category in response.json()["data"]] if response.status_code == 200 else []
    return {"categories": categories}

@app.post("/generate-podcast")
async def generate_podcast_endpoint(category_request: CategoryRequest):
    """
    Expects a JSON payload with the selected category. It will:
      - Retrieve blogs filtered by the given category.
      - Generate a PDF (with blog titles and descriptions).
      - Upload the PDF to Cloudinary.
      - Pass the PDF URL to the PlayNote API for podcast generation.
    
    Example JSON Payload:
    {
        "category": "Renewables"
    }
    """
    selected_category = category_request.category
    if not selected_category:
        raise HTTPException(status_code=400, detail="Category is required")
    
    # Fetch all blogs from the Strapi API
    all_blogs = get_all_blog_with_pagination()
    if not all_blogs:
        raise HTTPException(status_code=404, detail="No blogs found")
    
    # Filter blogs by selected category (case-insensitive)
    filtered_blogs = [
        blog for blog in all_blogs
        if blog.get('category', '').lower() == selected_category.lower()
    ]
    
    if not filtered_blogs:
        raise HTTPException(status_code=404, detail=f"No blogs found for category: {selected_category}")
    
    # Create a PDF containing the title and description for each filtered blog
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    
    # Add header text
    pdf.cell(200, 10, txt=f"Blogs for Category: {selected_category}", ln=True, align='C')
    pdf.ln(10)
    
    # Write each blog's title and description into the PDF
    for blog in filtered_blogs:
        # Replace unsupported characters with '?'
        title = blog.get("title", "No Title").encode("latin-1", "replace").decode("latin-1")
        description = blog.get("description", "No Description").encode("latin-1", "replace").decode("latin-1")
        print("Title of Blog: ", title)
        print("Title of Body: ", description)
        pdf.set_font("Arial", 'B', size=12)
        pdf.multi_cell(0, 10, txt=f"Title: {title}")
        pdf.set_font("Arial", size=12)
        pdf.multi_cell(0, 10, txt=f"Description: {description}")
        pdf.ln(10)
    
    # Save the PDF locally (filename based on the category)
    pdf_file_path = f"{selected_category}_blogs.pdf"
    pdf.output(pdf_file_path)
    
    # Upload the PDF to Cloudinary
    pdf_url = upload_pdf(pdf_file_path)
    if not pdf_url:
        raise HTTPException(status_code=500, detail="Failed to upload PDF")
    
    # Generate the podcast using the uploaded PDF URL
    podcast_result = generate_podcast(pdf_url)
    
    return {
        "pdf_url": pdf_url,
        "podcast_result": podcast_result
    }


@app.get("/playnote-status")
async def playnote_status(playNoteId: str = Query(..., description="The PlayNote ID to check the status for")):
    """
    Checks the status of a PlayNote using its ID.
    
    Query Parameter:
      - playNoteId: The ID returned when the PlayNote was initially created.
    
    Returns:
      - If the status is 'completed', returns the audio URL.
      - If the status is 'generating', instructs the user to wait.
      - Otherwise, returns an error message.
    """
    # Retrieve PlayNote credentials from environment variables
    api_key = "ak-"
    user_id = ""
    
    if not api_key or not user_id:
        raise HTTPException(status_code=500, detail="PlayNote credentials not set in environment variables")
    
    # Depending on the API requirements, you might need to prefix the API key with "Bearer "
    # For example: "Authorization": f"Bearer {api_key}"
    headers = {
        "Authorization": api_key,
        "X-USER-ID": user_id,
        "Accept": "application/json"
    }
    
    # Double encode the PlayNoteId
    double_encoded_id = urllib.parse.quote(playNoteId, safe='')
    
    # Construct the status URL
    url = f"https://api.play.ai/api/v1/playnotes/{double_encoded_id}"
    
    response = requests.get(url, headers=headers)
    
    if response.status_code == 200:
        status_data = response.json()
        status = status_data.get('status', '')
        if status == 'completed':
            return {"status": "completed", "audioUrl": status_data.get("audioUrl")}
        elif status == 'generating':
            return {"status": "generating", "message": "Please wait while your PlayNote is being generated and try again later!"}
        else:
            raise HTTPException(status_code=500, detail="PlayNote creation was not successful, please try again")
    else:
        raise HTTPException(status_code=response.status_code, detail=response.text)
    
###########################################
# Run the FastAPI App
###########################################

if __name__ == '__main__':
    uvicorn.run("app:app", host="127.0.0.1", port=8089, reload=True)



