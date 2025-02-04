from Report import create_app  # Import the create_app function

app = create_app()  # Create the Flask app instance

if __name__ == "__main__":
    app.run()  # This allows running the app directly (not needed for Gunicorn)
