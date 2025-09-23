import os
import time
import glob
import traceback
import numpy as np
from pathlib import Path
from psycopg2.extras import RealDictCursor
from multiprocessing import cpu_count
from concurrent.futures import ProcessPoolExecutor, as_completed

from pydub import AudioSegment
from pydub.silence import detect_nonsilent

from src.utils.db import get_db_connection
from src.utils import default_logger as logger


class Preprocessor:
    def __init__(self, feed_id, current_feed_path):
        self.feed_id = feed_id
        self.feed_name = "placeholder" 
        self.current_feed_path = Path(current_feed_path)
        self.min_silence_len = None
        self.silence_thresh = None
        self.cut_silence = False

        self.original_total_duration = 0
        self.preprocessed_total_duration = 0

        conn = get_db_connection()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as curr:
                curr.execute(
                    """
                    SELECT
                        name,
                        cut_silence,
                        min_silence_length,
                        silence_threshold
                    FROM feeds 
                    WHERE id = %s
                    """, (self.feed_id,)
                )
                res = curr.fetchone()
                if res is not None:
                    self.feed_name = res['name']
                    self.cut_silence = res['cut_silence']
                    self.min_silence_len = res['min_silence_length']
                    self.silence_thresh = res['silence_threshold']

                    if self.silence_thresh is not None:
                        self.silence_thresh = float(self.silence_thresh)
                    if self.min_silence_len is not None:
                        self.min_silence_len = int(self.min_silence_len)

                else:
                    logger.warning("No data received from feed_configs")
        finally:
            conn.close()
        
        logger.info(f"cut_silence: {self.cut_silence}")
        logger.info(f"min_silence_len: {self.min_silence_len}")
        logger.info(f"silence_thresh: {self.silence_thresh}")

    def _get_audio_directory(self) -> Path:
        """Get the audio directory path."""
        return self.current_feed_path / "audio"
    
    def _get_abridged_directory(self) -> Path:
        """Get the abridged directory path."""
        return self.current_feed_path / "abridged"
    
    def _get_mp3_files(self) -> list[Path]:
        """Get sorted list of MP3 files in the audio directory."""
        audio_dir = self._get_audio_directory()
        return sorted(audio_dir.glob("*.mp3"))
    
    def _get_abridged_files(self) -> list[Path]:
        """Get sorted list of abridged MP3 files."""
        abridged_dir = self._get_abridged_directory()
        return sorted(abridged_dir.glob("*.mp3"))
    
    def _get_output_path(self, input_path: Path, output_dir: Path) -> Path:
        """Generate output path for an abridged file."""
        return output_dir / input_path.name
    
    def _get_final_path(self, abridged_path: Path) -> Path:
        """Generate final path when moving abridged file to audio directory."""
        return self._get_audio_directory() / abridged_path.name
    
    def _get_file_extension(self, file_path: Path) -> str:
        """Extract file extension from path."""
        return file_path.suffix.lstrip('.')

    def run(self) -> None:
        if not self.cut_silence:
            return None

        output_dir = self._get_abridged_directory()
        output_dir.mkdir(exist_ok=True)

        mp3_paths = self._get_mp3_files()

        # Filter out already processed files for early exit
        unprocessed_paths = []
        for mp3_path in mp3_paths:
            output_path = self._get_output_path(mp3_path, output_dir)
            if not output_path.exists():
                unprocessed_paths.append(mp3_path)

        if not unprocessed_paths:
            logger.info("All files already processed, skipping preprocessing")
            return None

        logger.info(f"Preprocessing {len(unprocessed_paths)} files ({len(mp3_paths) - len(unprocessed_paths)} already processed)")

        # Determine optimal number of processes
        num_processes = min(len(unprocessed_paths), max(1, cpu_count() - 1))
        logger.info(f"Using {num_processes} processes")

        start_time = time.time()

        # Use ProcessPoolExecutor for better resource management and progress tracking
        with ProcessPoolExecutor(max_workers=num_processes) as executor:
            # Submit all tasks
            future_to_path = {
                executor.submit(
                    process_file_optimized,
                    mp3_path,
                    output_dir,
                    self.min_silence_len,
                    self.silence_thresh
                ): mp3_path for mp3_path in unprocessed_paths
            }

            # Process results as they complete
            processed_count = 0
            for future in as_completed(future_to_path):
                mp3_path = future_to_path[future]
                try:
                    original_dur, processed_dur = future.result()
                    if original_dur is not None and processed_dur is not None:
                        self.original_total_duration += original_dur
                        self.preprocessed_total_duration += processed_dur
                    processed_count += 1

                    # Progress logging every 10% or 10 files, whichever is smaller
                    log_interval = max(1, min(10, len(unprocessed_paths) // 10))
                    if processed_count % log_interval == 0:
                        progress = (processed_count / len(unprocessed_paths)) * 100
                        logger.info(f"Progress: {processed_count}/{len(unprocessed_paths)} ({progress:.1f}%)")

                except Exception as exc:
                    logger.error(f"File {mp3_path} generated an exception: {exc}")

        end_time = time.time()
        execution_time = end_time - start_time

        logger.info(f"Total execution time: {execution_time:.2f} seconds")
        if len(unprocessed_paths) > 0:
            logger.info(f"Average time per file: {execution_time / len(unprocessed_paths):.2f} seconds")

        abridged_paths = self._get_abridged_files()

        logger.info(f"Keeping {len(abridged_paths)} abridged files in separate directory")
        logger.info(f"Abridged files are available in: {output_dir}")

        logger.info(f"Preprocessing complete for {self.feed_name}")
        if self.original_total_duration > 0:
            logger.info(f"Total original duration: {self.original_total_duration:.2f}s")
            logger.info(f"Total preprocessed duration: {self.preprocessed_total_duration:.2f}s")
            logger.info(
                f"Total reduction: {100 - (self.preprocessed_total_duration / self.original_total_duration * 100):.1f}%")

    def process_file(self, mp3_path, output_dir, min_silence_len, silence_thresh):
        """Method to process a single file - returns tuple of (original_duration, processed_duration)"""
        try:
            mp3_path = Path(mp3_path)
            output_dir = Path(output_dir)
            output_path = self._get_output_path(mp3_path, output_dir)

            if output_path.exists():
                logger.info(f"Skipping {mp3_path} as {output_path} already exists")
                return None, None

            start_time = time.time()
            # logger.info(f"Processing {mp3_path}...")
            audio = AudioSegment.from_file(str(mp3_path))

            logger.info(f"Determining nonsilent ranges for {mp3_path.name}")
            nonsilent_ranges = detect_nonsilent(
                audio,
                min_silence_len=min_silence_len,
                silence_thresh=silence_thresh
            )

            if not nonsilent_ranges:
                logger.warning(f"No non-silent ranges found in {mp3_path}")
                return None, None

            output_audio = AudioSegment.empty()
            logger.info(f"Processing {mp3_path.name} with {len(nonsilent_ranges)} nonsilent ranges")
            for start_i, end_i in nonsilent_ranges:
                output_audio += audio[start_i:end_i]

            file_extension = self._get_file_extension(output_path)
            output_audio.export(str(output_path), format=file_extension)
            stop_time = time.time()

            original_duration = len(audio) / 1000
            processed_duration = len(output_audio) / 1000
            time_to_process = stop_time - start_time

            logger.info(f"Finished Processing: {output_path.name} in {time_to_process:.2f} seconds: {original_duration:.2f} -> {processed_duration:.2f} ")
            return original_duration, processed_duration

        except Exception as e:
            logger.error(f"Error processing {mp3_path}: {str(e)}")
            traceback.print_exc()
            return None, None


def process_file_optimized(mp3_path, output_dir, min_silence_len, silence_thresh):
    """
    Optimized version of process_file with memory-efficient techniques.
    Returns tuple of (original_duration, processed_duration)
    """
    try:
        mp3_path = Path(mp3_path)
        output_dir = Path(output_dir)
        output_path = output_dir / mp3_path.name

        if output_path.exists():
            # Return early with None values to indicate skip
            return None, None

        start_time = time.time()

        # Load audio with optimized settings for faster processing
        audio = AudioSegment.from_file(str(mp3_path))

        # Early exit for very short files (< 5 seconds)
        if len(audio) < 5000:  # 5 seconds in milliseconds
            logger.info(f"Skipping {mp3_path.name} - too short ({len(audio)/1000:.1f}s)")
            return None, None

        # Pre-filter silence detection with chunked processing for large files
        chunk_length_ms = 30000  # 30 seconds
        if len(audio) > chunk_length_ms * 4:  # Only chunk if > 2 minutes
            nonsilent_ranges = _detect_nonsilent_chunked(
                audio, min_silence_len, silence_thresh, chunk_length_ms
            )
        else:
            nonsilent_ranges = detect_nonsilent(
                audio,
                min_silence_len=min_silence_len,
                silence_thresh=silence_thresh
            )

        if not nonsilent_ranges:
            logger.warning(f"No non-silent ranges found in {mp3_path.name}")
            return None, None

        # Use more efficient concatenation with pre-allocated list
        audio_segments = []
        total_length = 0

        for start_i, end_i in nonsilent_ranges:
            segment = audio[start_i:end_i]
            audio_segments.append(segment)
            total_length += len(segment)

        # Concatenate all segments at once (more efficient than +=)
        if audio_segments:
            output_audio = sum(audio_segments)
        else:
            logger.warning(f"No audio segments to process in {mp3_path.name}")
            return None, None

        # Export with optimized parameters
        file_extension = output_path.suffix.lstrip('.')
        export_params = {"format": file_extension}

        # Use higher compression for MP3 to reduce I/O time
        if file_extension.lower() == "mp3":
            export_params.update({
                "bitrate": "128k",  # Reasonable quality vs size tradeoff
                "parameters": ["-q:a", "2"]  # Good quality, faster encoding
            })

        output_audio.export(str(output_path), **export_params)

        stop_time = time.time()
        original_duration = len(audio) / 1000
        processed_duration = len(output_audio) / 1000
        time_to_process = stop_time - start_time

        logger.info(f"Processed {output_path.name} in {time_to_process:.2f}s: {original_duration:.1f}s -> {processed_duration:.1f}s")
        return original_duration, processed_duration

    except Exception as e:
        logger.error(f"Error processing {mp3_path}: {str(e)}")
        return None, None


def _detect_nonsilent_chunked(audio, min_silence_len, silence_thresh, chunk_length_ms):
    """
    Process large audio files in chunks to reduce memory usage and improve performance.
    """
    total_length = len(audio)
    all_nonsilent_ranges = []

    for start_ms in range(0, total_length, chunk_length_ms):
        end_ms = min(start_ms + chunk_length_ms, total_length)
        chunk = audio[start_ms:end_ms]

        # Detect non-silent ranges in this chunk
        chunk_ranges = detect_nonsilent(
            chunk,
            min_silence_len=min_silence_len,
            silence_thresh=silence_thresh
        )

        # Adjust ranges to global coordinates
        adjusted_ranges = [(start + start_ms, end + start_ms) for start, end in chunk_ranges]
        all_nonsilent_ranges.extend(adjusted_ranges)

    # Merge overlapping or adjacent ranges (within min_silence_len)
    if not all_nonsilent_ranges:
        return []

    merged_ranges = []
    current_start, current_end = all_nonsilent_ranges[0]

    for start, end in all_nonsilent_ranges[1:]:
        # If ranges are close enough, merge them
        if start - current_end <= min_silence_len:
            current_end = max(current_end, end)
        else:
            merged_ranges.append((current_start, current_end))
            current_start, current_end = start, end

    merged_ranges.append((current_start, current_end))
    return merged_ranges