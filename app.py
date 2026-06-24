from flask import Flask
from config import Config
from extensions import limiter

app = Flask(__name__)
app.config.from_object(Config)

limiter.init_app(app)

from routes.pages import pages_bp

app.register_blueprint(pages_bp)


if __name__ == "__main__":
    app.run()
