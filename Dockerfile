FROM python:3.11
RUN apt-get update && apt-get install -y libpq-dev
COPY . /app
WORKDIR /app
RUN pip install -r requirements.txt
EXPOSE 8000
CMD ["fastapi", "run", "main.py", "--port", "8000"]
