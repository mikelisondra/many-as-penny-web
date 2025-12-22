import os
import requests
from flask import Flask, render_template, request, redirect, url_for, flash, session
from dotenv import load_dotenv
from supabase import create_client, Client
from check_alerts import check_all_alerts

# Imports for Login System
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user

# IMPORTS for Brevo API
import brevo_python
from brevo_python.rest import ApiException
from brevo_python.models.send_smtp_email import SendSmtpEmail

# Load environment variables from .env file
load_dotenv()

# Initialize the Flask application
app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY') 

# Connect to Finnhub
FINNHUB_API_KEY = os.getenv('FINNHUB_API_KEY')
FINNHUB_BASE_URL = 'https://finnhub.io/api/v1'

# Connect to Supabase
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Get Brevo API Credentials
BREVO_API_KEY = os.getenv('BREVO_API_KEY')
BREVO_SENDER = os.getenv('BREVO_SENDER') # Validated 'From' email

# Configure Brevo API
configuration = brevo_python.Configuration()
configuration.api_key['api-key'] = BREVO_API_KEY
api_instance = brevo_python.TransactionalEmailsApi(brevo_python.ApiClient(configuration))

# Login Manager Setup
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'register' # Redirect to /register if not logged in
login_manager.login_message = None     # THIS IS THE FIX
login_manager.login_message_category = 'info' 

# User Class for Flask-Login
class User(UserMixin):
    def __init__(self, id, email):
        self.id = id
        self.email = email

@login_manager.user_loader
def load_user(user_id):
    """Loads a user object from the session for Flask-Login."""
    email = session.get('email')
    return User(id=user_id, email=email)

# Brevo API Email Function
def send_email_alert(target_email, symbol, name, alert_type, current_price, target_price):
    """Builds and sends an HTML email alert using the Brevo API."""
    
    if not BREVO_API_KEY or not BREVO_SENDER:
        print("Brevo keys not set in .env. Skipping email.")
        return

    if not target_email:
        print(f"No alert_email set for {symbol}. Skipping email.")
        return

    # Set dynamic content
    if alert_type == 'high':
        subject = f"✅ High Price Alert for {symbol}!"
        color = "#4CAF50" # Green
        alert_text = "hit high target"
    else: # 'low'
        subject = f"🔻 Low Price Alert for {symbol}!"
        color = "#dc3545" # Red
        alert_text = "hit low target"
        
    # HTML EMAIL
    html_content = f"""
    <html>
    <head>
      <style>
        body {{ font-family: Arial, sans-serif; line-height: 1.6; background-color: #f4f4f4; padding: 20px; }}
        .container {{ max-width: 600px; margin: auto; background-color: #ffffff; padding: 30px; border-radius: 10px; box-shadow: 0 4px 10px rgba(0,0,0,0.1); }}
        .header {{ color: #333; text-align: center; }}
        .alert-title {{ color: {color}; text-align: center; }}
        .content {{ font-size: 1.1em; color: #555; }}
        .data-box {{ background-color: #f9f9f9; padding: 15px; border-radius: 5px; text-align: center; font-size: 1.2em; }}
        .footer {{ color: #888; font-size: 0.9em; text-align: center; margin-top: 20px; }}
      </style>
    </head>
    <body>
      <div class="container">
        <h2 class="header">Many As Penny Alert!</h2>
        <h3 class="alert-title">{symbol} ({name}) {alert_text}</h3>
        <p class="content">Hello from MAP App,</p>
        <p class="content">This is an automated alert to let you know that <strong>{symbol}</strong> has reached a price of <strong>${current_price:,.2f}</strong>.</p>
        <div class="data-box">
          <p style="margin: 5px 0; color: #333;"><strong>Target Price:</strong> ${target_price:,.2f}</p>
          <p style="margin: 5px 0; color: {color};"><strong>Current Price:</strong> ${current_price:,.2f}</p>
        </div>
        <p class="footer">- MAP App</p>
      </div>
    </body>
    </html>
    """
    
    # Create the email object
    send_smtp_email = SendSmtpEmail(
        to=[{"email": target_email}],
        sender={"email": BREVO_SENDER, "name": "MAP Alert"},
        subject=subject,
        html_content=html_content
    )
    
    # Send the email
    try:
        api_response = api_instance.send_transac_email(send_smtp_email)
        print(f"Email sent via Brevo API to {target_email}. Message ID: {api_response.message_id}")
    except ApiException as e:
        print(f"Error: Unable to send Brevo email. {e}")


# Stock data and profile functions
def get_stock_quote(symbol):
    """Fetches stock quote data from Finnhub API."""
    try:
        url = f'{FINNHUB_BASE_URL}/quote?symbol={symbol}&token={FINNHUB_API_KEY}'
        response = requests.get(url)
        response.raise_for_status() 
        data = response.json()
        
        # VALIDATION: A successful quote has a current price 'c' that is not 0
        if data.get('c') == 0 and data.get('h') == 0:
            print(f"Found symbol {symbol} but it has no price data (likely not a valid stock).")
            return {'symbol': symbol, 'error': 'No valid price data found for ticker.'}
            
        data['symbol'] = symbol 
        return {
            'symbol': symbol, 'current_price': data.get('c'),
            'price_change': data.get('d'), 'percent_change': data.get('dp'),
            'opening_price': data.get('o'), 'high_price': data.get('h'),
            'low_price': data.get('l')
        }
    except requests.exceptions.RequestException as e:
        print(f"Error fetching quote for {symbol}: {e}")
        return {'symbol': symbol, 'error': 'Failed to fetch quote'}

def search_for_stock(search_term):
    """Uses Finnhub Search to find the best match for a search term."""
    try:
        url = f'{FINNHUB_BASE_URL}/search?q={search_term}&token={FINNHUB_API_KEY}'
        response = requests.get(url)
        response.raise_for_status() 
        data = response.json()
        
        if data.get('result') and len(data['result']) > 0:
            return data['result'][0] 
        else:
            return None
            
    except requests.exceptions.RequestException as e:
        print(f"Error searching for stock {search_term}: {e}")
        return None


# Register Route
@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('home')) 
    
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        try:
            user = supabase.auth.sign_up({
                "email": email,
                "password": password,
            })
            flash('Registration successful! Please check your email to confirm.', 'success')
            return redirect(url_for('login'))
        except Exception as e:
            flash(f'Registration failed: {str(e)}', 'error')
            
    return render_template('register.html')

# Login Route
@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('home'))
    
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        try:
            user_session = supabase.auth.sign_in_with_password({
                "email": email,
                "password": password,
            })
            
            user_obj = User(id=user_session.user.id, email=user_session.user.email)
            login_user(user_obj) 
            
            session['email'] = user_session.user.email
            
            return redirect(url_for('home'))
        except Exception as e:
            flash(f'Login failed. Check email/password.', 'error')
            
    return render_template('login.html')

# Logout Route
@app.route('/logout')
@login_required
def logout():
    logout_user() 
    session.pop('email', None) 
    return redirect(url_for('login'))


# Homepage Route
@app.route('/')
@login_required 
def home():
    """Renders the homepage with a list of stock data for the logged-in user."""
    
    user_id = current_user.id
    
    stocks_response = supabase.table('stocks').select('id, symbol, name').eq('user_id', user_id).execute()
    stocks = stocks_response.data 
    
    alerts_response = supabase.table('alerts').select('*').eq('user_id', user_id).execute()
    all_alerts = alerts_response.data
    
    for stock in stocks:
        stock_data = get_stock_quote(stock['symbol'])
        stock.update(stock_data) 
        
        stock['alerts'] = [alert for alert in all_alerts if alert['stock_id'] == stock['id']]
            
    return render_template('index.html', stocks=stocks)

# Add Stock Function
@app.route('/add_stock', methods=['POST'])
@login_required 
def add_stock():
    """Searches for a stock and adds it to the user's database."""
    search_term = request.form.get('new_stock_symbol')
    user_id = current_user.id 
    
    if not search_term:
        return redirect(url_for('home'))
        
    stock_data = search_for_stock(search_term)
    
    if stock_data:
        new_symbol = stock_data.get('symbol')
        company_name = stock_data.get('description') 
        
        test_quote = get_stock_quote(new_symbol)
        
        if test_quote.get('error'):
            flash(f"Found '{new_symbol}' but could not fetch price data. It may be an invalid or non-US ticker.", "error")
            return redirect(url_for('home'))
            
        try:
            existing = supabase.table('stocks').select('id').eq('symbol', new_symbol).eq('user_id', user_id).execute()
            if not existing.data:
                supabase.table('stocks').insert({
                    'symbol': new_symbol,
                    'name': company_name,
                    'user_id': user_id 
                }).execute()
            else:
                flash(f"'{new_symbol}' is already in your list.", "error")
                
        except Exception as e:
            print(f"Error adding stock: {e}")
            flash("Error adding stock to database.", "error")
            
    else:
        flash(f"No stock found for '{search_term}'. Please try a different name or ticker.", "error")

    return redirect(url_for('home'))


# Delete Stock Function
@app.route('/delete_stock', methods=['POST'])
@login_required
def delete_stock():
    """Deletes a stock from the database."""
    stock_id_to_delete = request.form.get('stock_id')
    user_id = current_user.id
    
    if stock_id_to_delete:
        try:
            supabase.table('stocks').delete().eq('id', stock_id_to_delete).eq('user_id', user_id).execute()
        except Exception as e:
            print(f"Error deleting stock: {e}")
            
    return redirect(url_for('home'))


# Add Alert Function
@app.route('/add_alert', methods=['POST'])
@login_required
def add_alert():
    """Adds a new user alert to the alerts table."""
    stock_id = request.form.get('stock_id')
    email = request.form.get('alert_email')
    price = request.form.get('target_price')
    alert_type = request.form.get('alert_type')
    user_id = current_user.id
    
    if stock_id and email and price and alert_type:
        try:
            stock_check = supabase.table('stocks').select('id').eq('id', stock_id).eq('user_id', user_id).execute()
            if not stock_check.data:
                flash("Error: You do not own this stock.", "error")
                return redirect(url_for('home'))

            supabase.table('alerts').insert({
                'stock_id': stock_id,
                'alert_email': email,
                'target_price': price,
                'alert_type': alert_type,
                'is_triggered': False,
                'user_id': user_id
            }).execute()
        except Exception as e:
            print(f"Error adding alert: {e}")
    
    return redirect(url_for('home'))


# Delete Alert Function
@app.route('/delete_alert', methods=['POST'])
@login_required
def delete_alert():
    """Deletes a single alert from the database."""
    alert_id = request.form.get('alert_id')
    user_id = current_user.id
    
    if alert_id:
        try:
            supabase.table('alerts').delete().eq('id', alert_id).eq('user_id', user_id).execute()
        except Exception as e:
            print(f"Error deleting alert: {e}")
    
    return redirect(url_for('home'))


if __name__ == '__main__':
    app.run(debug=True)

# Secret route to be run by UptimeRobot
@app.route('/run-alert-check')
def run_alert_check():

    secret = request.args.get('secret')

    if secret == os.getenv('CRON_SECRET'):
        check_all_alerts()
        return "Alert check finished.", 200
    else:
        return "Error: Invalid secret key.", 403