import os
import logging
import psycopg2
import tempfile
import traceback
import shutil
import requests
import librosa
import time
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

import numpy as np
from pprint import pprint
from PIL import Image, ImageDraw
from typing import Tuple, List, Dict, Optional
from psycopg2.extras import RealDictCursor

from src.logger import default_logger as logger
from src.utils.db import get_supabase_client


class WaveformHandler:
    def __init__(self):
        self.supabase = get_supabase_client()
        self.logger = logger
        self.temp_dir = tempfile.mkdtemp()

    def process_incident_waveform(self, incident_id: str):

        try:

            res = (
                self.supabase.table('incidents')
                .select('audio_path')
                .eq('incident_id', incident_id)
                .execute()
            )
            
            if len(res.data) == 0:
                self.logger.error(f"Incident {incident_id} not found")
                return

            audio_url = res.data[0]['audio_path']
            audio_file_path = self.download_audio_file(audio_url, incident_id)
            self.logger.info(f"Downloaded audio file to {audio_file_path}")

            waveform_img_path = self.generate_waveform_img(audio_file_path, incident_id)
            self.logger.info(f"Generated waveform image to {waveform_img_path}")
            

            waveform_img_url = self.upload_image_to_cf_images_with_retry(waveform_img_path)
            if waveform_img_url:
                self.logger.info(f"Uploaded waveform image to {waveform_img_url}")
                self.add_waveform_to_incident(incident_id, waveform_img_url)
            else:
                self.logger.error(f"Failed to upload waveform image for incident {incident_id}")
        
        except Exception as e:
            traceback.print_exc()
            self.logger.error(f"Error processing incident {incident_id}: {e}")
        finally:
            self.cleanup()

    


    def download_audio_file(self, audio_url: str, incident_id: str) -> str:

        try:
            # Create a temporary directory that will persist
            temp_dir = self.temp_dir
            # Determine file extension from URL
            file_extension = os.path.splitext(audio_url)[1].lower()
            if not file_extension or file_extension not in ['.mp3', '.m4a']:
                # Default to mp3 if extension is not recognized
                file_extension = '.mp3'
                
            # Use incident_id as filename
            filename = f"{incident_id}{file_extension}"
                
            # Full path to the downloaded file
            output_path = os.path.join(temp_dir, filename)
            
            # Download the file
            response = requests.get(audio_url, stream=True)
            response.raise_for_status()  # Raise an exception for HTTP errors
            
            # Write the file to disk
            with open(output_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            
            self.logger.info(f"Downloaded audio file to {output_path}")
            return output_path
            
        except Exception as e:
            self.logger.error(f"Error downloading audio file: {e}")
            return ""



    def generate_waveform_img(
        self,
        audio_path: str,
        incident_id: str,
        width: int = 800,
        height: int = 200,
        color: Tuple[int, int, int] = (0, 255, 0)
    ) -> str:
        """
        Generate a waveform image from an audio file.
        Returns the path to the output PNG file.
        
        Parameters:
            audio_path (str): Path to the audio file
            output_path (str): Path to save the output PNG
            width (int): Width of the output image
            height (int): Height of the output image
            color (tuple): RGB color tuple for the waveform
        """
        try:
            self.logger.info(f'Generating waveform for {audio_path}')

            # Load the audio file
            # self.logger.info(f"Loading audio file: {audio_path}")

            y, sr = librosa.load(audio_path)
            
            # Calculate number of samples per pixel
            # self.logger.info(f"Calculating samples per pixel")
            samples_per_pixel = len(y) // width
            
            # Calculate the peak values for each pixel
            # self.logger.info(f"Calculating peak values")
            peaks = []
            for i in range(0, len(y), samples_per_pixel):
                chunk = y[i:i + samples_per_pixel]
                if len(chunk) > 0:
                    max_val = np.max(np.abs(chunk))
                    peaks.append(max_val)
            
            # Normalize peaks
            if peaks:
                # self.logger.info(f"Normalizing peaks")
                peaks = np.array(peaks)
                peaks = peaks / np.max(peaks)
            
            # Create image
            # self.logger.info(f"Creating image")
            img = Image.new('RGB', (width, height), 'black')
            draw = ImageDraw.Draw(img)
            
            # Calculate center line
            # self.logger.info(f"Calculating center line")
            center_line = height // 2
            
            # Draw waveform
            for x, peak in enumerate(peaks):
                if x >= width:
                    break
                    
                peak_height = int((height / 2) * peak)
                draw.line(
                    [(x, center_line + peak_height),
                    (x, center_line - peak_height)],
                    fill=color
                )
            
            # Save image
            output_path = os.path.join(self.temp_dir, f"{incident_id}_waveform.png")
            self.logger.info(f'Saving image to {output_path}')
            img.save(output_path, 'PNG')
            return output_path
        
        except Exception as e:
            self.logger.error(f"Error generating waveform image: {e}")
            return ""


    def _upload_image_to_cf_images(self, image_path: str) -> Optional[str]:
        account_id = os.getenv('CLOUDFLARE_IMAGES_ACCOUNT_ID')
        api_token = os.getenv('CLOUDFLARE_IMAGES_API_TOKEN')

        url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/images/v1"
        headers = {
            'Authorization': f'Bearer {api_token}'
        }
        files = {
            'file': open(image_path, 'rb')
        }

        response = requests.post(url, headers=headers, files=files)
        if response.status_code == 200:
            res_json = response.json()
            image_url = res_json['result']['variants'][0]
            return image_url
        else:
            self.logger.error(f"Error uploading image to cloudflare images: {response.text}")
            # Check if it's a quota exceeded error
            try:
                error_data = response.json()
                if 'quota' in error_data.get('errors', [{}])[0].get('message', '').lower():
                    self.logger.warning("Quota exceeded error detected")
                    return None
            except:
                pass
            return None


    def add_waveform_to_incident(self, incident_id: str, waveform_url: str) -> bool:
        try:
            res = (
                self.supabase.table('incidents')
                .update({'waveform_img_url': waveform_url})
                .eq('incident_id', incident_id)
                .execute()
            )
            self.logger.info(f"Added waveform to incident {incident_id}")
            return True

        except Exception as e:
            self.logger.error(f"Error adding waveform to incident: {e}")
            return False
    
    def _get_cloudflare_images_to_delete(self, limit: int = 1000) -> list[dict]:
        """
        Get oldest 1000 images from incidents table using psycopg2 with proper connection management.
        
        Returns:
            list[dict]: List of dictionaries containing id and waveform_img_url
        """
        # Database connection parameters
        USER = os.getenv("SUPABASE_USER")
        PASSWORD = os.getenv("SUPABASE_PASSWORD")
        HOST = os.getenv("SUPABASE_HOST")
        PORT = os.getenv("SUPABASE_PORT")
        DBNAME = os.getenv("SUPABASE_DATABASE_NAME")
        
        try:
            # Use context manager for proper connection handling
            with psycopg2.connect(
                host=HOST,
                database=DBNAME,
                user=USER,
                password=PASSWORD,
                port=PORT
            ) as conn:
                # Use RealDictCursor to return results as dictionaries
                with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                    query = f"""
                    SELECT id, waveform_img_url 
                    FROM incidents 
                    WHERE waveform_img_url IS NOT NULL
                    ORDER BY notification_creation_time ASC
                    LIMIT {limit};
                    """
                    
                    cursor.execute(query)
                    results = cursor.fetchall()
                    
                    # Convert RealDictRow objects to regular dictionaries
                    data = [dict(row) for row in results]
                    print(data)
                    return data
                    
        except Exception as e:
            print(f"Database connection failed: {e}")
            raise e




    def delete_cloudflare_image(self, image_id: str) -> bool:
        """
        Delete a single image from Cloudflare Images.
        Returns True if successful, False otherwise.
        """
        account_id = os.getenv('CLOUDFLARE_IMAGES_ACCOUNT_ID')
        api_token = os.getenv('CLOUDFLARE_IMAGES_API_TOKEN')
        
        url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/images/v1/{image_id}"
        headers = {
            'Authorization': f'Bearer {api_token}'
        }
        
        response = requests.delete(url, headers=headers)
        
        if response.status_code == 200:
            self.logger.info(f"Successfully deleted image {image_id}")
            return True
        else:
            self.logger.error(f"Error deleting image {image_id}: {response.text}")
            return False
        
    def _set_waveform_img_url_to_null(self, row_id: str) -> bool:
        try:
            res = (
                self.supabase.table('incidents')
                .update({'waveform_img_url': None})
                .eq('id', row_id)
                .execute()
            )
            logger.info(f"Set waveform_img_url to null for incident {row_id}")

        except Exception as e:

            logger.error(f"Error setting waveform_img_url to null: {e}")
            raise e

    def cleanup_old_images(self, count: int = 1000, max_workers: int = 10, delay_between_requests: float = 0.05) -> int:
        """
        Clean up old images with configurable concurrency settings.
        
        Args:
            count: Number of oldest images to delete
            max_workers: Number of concurrent threads (default: 10)
            delay_between_requests: Delay between API requests in seconds (default: 0.05)
            
        Returns:
            Number of successfully deleted images
        """
        self.logger.info(f"Starting bulk cleanup: {count} images, {max_workers} workers, {delay_between_requests}s delay")
        
        # Adjust max_workers based on rate limits
        if max_workers > 20:
            self.logger.warning(f"Reducing max_workers from {max_workers} to 20 to avoid rate limiting")
            max_workers = 20
        
        start_time = time.time()
        deleted_count = self._delete_oldest_images(count=count, max_workers=max_workers, delay_between_requests=delay_between_requests)
        end_time = time.time()
        
        duration = end_time - start_time
        rate = deleted_count / duration if duration > 0 else 0
        
        self.logger.info(f"Bulk cleanup completed: {deleted_count} images deleted in {duration:.2f}s ({rate:.2f} images/sec)")
        return deleted_count

    def _delete_oldest_images(self, count: int = 1000, max_workers: int = 10, delay_between_requests: float = 0.05) -> int:
        """
        Delete the oldest images from Cloudflare Images using concurrent execution.
        Returns the number of successfully deleted images.
        """
        self.logger.info(f"Attempting to delete {count} oldest images with {max_workers} workers")
        
        # Get all images sorted by creation date
        images = self._get_cloudflare_images_to_delete(limit=count)
        logger.info(f"Found {len(images)} images to delete")
        logger.info(f"Images: {images[:10]}")
        
        if not images:
            self.logger.warning("No images found to delete")
            return 0
        
        # Take the oldest images
        images_to_delete = images[:count]
        
        deleted_count = 0
        failed_count = 0
        lock = Lock()  # Thread-safe counter
        
        def delete_single_image(image_data):
            """Helper function to delete a single image and update database"""
            nonlocal deleted_count, failed_count
            
            waveform_img_url = image_data.get('waveform_img_url')
            if not waveform_img_url:
                return False
                
            image_id = waveform_img_url.split('/')[-2]
            
            try:
                if self.delete_cloudflare_image(image_id):
                    # Update database to set waveform_img_url to null
                    self._set_waveform_img_url_to_null(image_data.get('id'))
                    
                    with lock:
                        deleted_count += 1
                    
                    return True
                else:
                    with lock:
                        failed_count += 1
                    return False
                    
            except Exception as e:
                self.logger.error(f"Error deleting image {image_id}: {e}")
                with lock:
                    failed_count += 1
                return False
        
        # Use ThreadPoolExecutor for concurrent deletion
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all deletion tasks
            future_to_image = {
                executor.submit(delete_single_image, image): image 
                for image in images_to_delete
            }
            
            # Process completed tasks with rate limiting
            for future in as_completed(future_to_image):
                try:
                    result = future.result()
                    # Small delay to avoid overwhelming the API
                    time.sleep(delay_between_requests)
                except Exception as e:
                    self.logger.error(f"Unexpected error in thread: {e}")
                    with lock:
                        failed_count += 1
        
        logger.info(f"Successfully deleted {deleted_count} out of {len(images_to_delete)} images. Failed: {failed_count}")
        return deleted_count


    def upload_image_to_cf_images_with_retry(self, image_path: str, max_retries: int = 3) -> Optional[str]:
        """
        Upload image to Cloudflare Images with retry logic for quota exceeded errors.
        If quota is exceeded, deletes oldest images and retries.
        """
        for attempt in range(max_retries):
            try:
                result = self._upload_image_to_cf_images(image_path)
                
                if result:
                    return result
                
                # Check if the error was due to quota exceeded
                # We'll need to check the response from the previous call
                # For now, we'll assume any failed upload might be quota-related
                # and try deleting old images
                
                self.logger.warning(f"Upload attempt {attempt + 1} failed, attempting to free up space")
                
                # Delete oldest images to free up space
                deleted_count = self._delete_oldest_images(count=1000, max_workers=5, delay_between_requests=0.05)
                
                if deleted_count > 0:
                    self.logger.info(f"Deleted {deleted_count} old images, retrying upload")
                    # Wait a moment for the deletion to propagate
                    time.sleep(2)
                else:
                    self.logger.error("Failed to delete any images, cannot retry upload")
                    break
                    
            except Exception as e:
                self.logger.error(f"Error during upload attempt {attempt + 1}: {e}")
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)  # Exponential backoff
                else:
                    break
        
        self.logger.error(f"Failed to upload image after {max_retries} attempts")
        return None

    def cleanup(self):
        try:
            shutil.rmtree(self.temp_dir)
            self.logger.info(f"Cleaned up temp directory: {self.temp_dir}")
        except Exception as e:
            self.logger.error(f"Error cleaning up temp directory: {e}")





