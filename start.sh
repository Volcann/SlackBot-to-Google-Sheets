cd ~/Downloads/SlackBot/

python3 -m venv venv
source venv/bin/activate

pip install -r requirements.txt

cd project_level/
python3 manage.py runserver
