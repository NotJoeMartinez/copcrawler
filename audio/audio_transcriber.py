import os
import json
import hashlib
import datetime
from pathlib import Path
from openai import OpenAI
from pydub import AudioSegment
from psycopg2.extras import RealDictCursor
from concurrent.futures import ThreadPoolExecutor, as_completed

from src.utils.db import get_db_connection
from src.utils import default_logger as logger

class Transcriber:
    def __init__(
        self,
        current_feed_path: str,
        feed_id: str,
        model_id: str,
    ):

        self.current_feed_path = Path(current_feed_path)
        self.feed_id = feed_id
        self.model_id = model_id

        self.min_silence_len = None
        self.silence_thresh = None
        self.initial_prompt = None
        self.cut_silence = False 

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
                    self.cut_silence = res['cut_silence']
                    self.min_silence_len = res['min_silence_length']
                    self.silence_thresh = res['silence_threshold']
                else:
                    logger.warning("No data received from feed_configs")
        finally:
            conn.close()
    
    def _get_audio_directory(self) -> Path:
        """Get the audio directory path."""
        return self.current_feed_path / "audio"
    
    def _get_abridged_directory(self) -> Path:
        """Get the abridged directory path."""
        return self.current_feed_path / "abridged"
    
    def _get_transcript_directory(self) -> Path:
        """Get the transcript directory path."""
        return self.current_feed_path / "transcripts"
    
    def _get_mp3_files(self) -> list[Path]:
        """Get sorted list of MP3 files, preferring abridged files when available."""
        abridged_dir = self._get_abridged_directory()
        
        # Check if abridged directory exists and has MP3 files
        if abridged_dir.exists():
            abridged_files = sorted(abridged_dir.glob("*.mp3"))
            if abridged_files:
                logger.info(f"Using {len(abridged_files)} abridged MP3 files from {abridged_dir}")
                return abridged_files
        
        # Fall back to original audio files
        audio_dir = self._get_audio_directory()
        original_files = sorted(audio_dir.glob("*.mp3"))
        logger.info(f"Using {len(original_files)} original MP3 files from {audio_dir}")
        return original_files
        
    def transcribe_audio(self):
        logger.info(f"Transcribing audio for feed {self.feed_id}")

        transcript_dir = self._get_transcript_directory()
        transcript_dir.mkdir(exist_ok=True)
        mp3_files = self._get_mp3_files()
        total_files = len(mp3_files)

        logger.info(f"Estimating cost to transcribe {total_files} files")
        full_audio_length = self._get_full_audio_length(mp3_file_paths=mp3_files)
        const_per_min_to_transcribe = 0.00045
        expected_price = (full_audio_length / 60) * const_per_min_to_transcribe
        logger.info(f"Transcribing {full_audio_length:.2f}s of Audio")
        logger.info(f"Expected price to transcribe: ${expected_price:.2f}")

        durations = []

        with ThreadPoolExecutor(max_workers=8) as executor:
            future_to_audio_file = {executor.submit(self.transcribe_file, audio_file): audio_file for audio_file in mp3_files}
            for count, future in enumerate(as_completed(future_to_audio_file), 1):
                audio_file = future_to_audio_file[future]
                try:
                    duration = future.result()
                    if duration:
                        durations.append(duration)
                    if count % 10 == 0:
                        logger.info(f"Transcribed {count} of {total_files} files")
                except Exception as e:
                    logger.error(f"Error processing {audio_file}: {e}")

        total_duration = sum(durations)
        logger.info(f"Full audio length: {total_duration}")


    def transcribe_file(self, audio_file):
        logger.info(f"Transcribing file: {audio_file}")
        client = OpenAI(
            api_key=os.getenv("DEEPINFRA_API_KEY"),
            base_url="https://api.deepinfra.com/v1/openai",
        )

        audio_file = Path(audio_file)
        audio_fname = audio_file.name
        date_dir = audio_file.parent.parent.stem
        recorded_timestamp = audio_file.stem.split("-")[0]
        file_hash = self.get_shasum(audio_file)
        transcript_fname = audio_file.stem + ".json"
        transcript_path = self._get_transcript_directory() / transcript_fname

        if transcript_path.exists():
            return None

        logger.info(f"officially transcribing file: {audio_file}")
        transcript = client.audio.transcriptions.create(
            file=open(str(audio_file), "rb"),
            model=f"openai/{self.model_id}",
            language="en",
            response_format="verbose_json",
            timestamp_granularities=["segment", "word"]
        )

        output = {
            "text": transcript.text,
            "metadata": {
                "recorded_timestamp": recorded_timestamp,
                "date_dir": date_dir,
                "feed_id": self.feed_id,
                "file_transcribed": audio_fname,
                "duration": transcript.duration,
                "spend": (transcript.duration / 60) * 0.00045,
                "provider": "DEEPINFRA",
                "file_hash": file_hash,
                "sst_model": self.model_id.upper(),
                "model": {
                    "model_size": self.model_id,
                    "device": "API",
                    "compute_type": "NULL",
                    "num_workers": "NULL",
                    "cpu_threads": "NULL"
                },
                "transcription_options": {
                    "best_of": "NULL",
                    "patience": "NULL",
                    "repetition_penalty": "NULL",
                    "no_repeat_ngram_size": "NULL",
                    "log_prob_threshold": "NULL",
                    "no_speech_threshold": "NULL"
                }
            },
            "segments": [
                {
                    "id": segment.id,
                    "text": segment.text,
                    "start": segment.start,
                    "end": segment.end,
                    "seek": segment.seek,
                    "temperature": segment.temperature,
                    "avg_logprob": segment.avg_logprob,
                    "compression_ratio": segment.compression_ratio,
                    "no_speech_prob": segment.no_speech_prob,
                    "tokens": segment.tokens
                }
                for segment  in transcript.segments
            ],
            "words": [
                {
                    "text": word.word,
                    "start": word.start,
                    "end": word.end
                }
                for word in transcript.words
            ]
        }

        with open(str(transcript_path), "w", encoding="utf-8") as f:
            json.dump(output, f)

        return float(transcript.duration)

    def get_shasum(self, file_path: Path) -> str:
        sha1 = hashlib.sha1()

        with open(str(file_path), 'rb') as file:
            while chunk := file.read(8192):
                sha1.update(chunk)

        return sha1.hexdigest()

    def _get_full_audio_length(self, mp3_file_paths: list[Path]) -> float:
        """Calculate total audio length for the given MP3 files."""
        total_seconds = 0
        for file_path in mp3_file_paths:
            audio = AudioSegment.from_file(str(file_path))
            file_length = len(audio)
            total_seconds += (file_length / 1000)
        
        return total_seconds
