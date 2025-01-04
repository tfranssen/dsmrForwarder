# Use an official Python base image
FROM python:3.9-slim

# Copy the script into the container
COPY main.py /app/main.py

# Set the working directory
WORKDIR /app

# Install dependencies if needed
# RUN pip install -r requirements.txt

# Set the command to run the Python script
CMD ["python3", "main.py"]
