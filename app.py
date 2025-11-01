import os
import requests
from flask import Flask, render_template, request, redirect, url_for, flash
from dotenv import load_dotenv
from supabase import create_client, Client

# --- NEW IMPORTS for Brevo API ---
import brevo_python
from brevo_python.rest import ApiException
from brevo_python.models.send_smtp_email import SendSmtpEmail

# Load environment variables from .env file
load_dotenv()

# Initialize the Flask application
app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY') # Correct key

# Connect to Finnhub
FINNHUB_API_KEY = os.getenv('FINNHUB_API_KEY')
FINNHUB_BASE_URL = 'https://finnhub.io/api/v1'

# Connect to Supabase
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- NEW: Get Brevo API Credentials ---
BREVO_API_KEY = os.getenv('BREVO_API_KEY')
BREVO_SENDER = os.getenv('BREVO_SENDER') # Your validated 'From' email

# --- NEW: Configure Brevo API ---
configuration = brevo_python.Configuration()
configuration.api_key['api-key'] = BREVO_API_KEY
api_instance = brevo_python.TransactionalEmailsApi(brevo_python.ApiClient(configuration))


# --- NEW: Brevo API Email Function (replaces SMTP) ---
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

def get_stock_profile(symbol):
    """Fetches static company profile data (like name) from Finnhub API."""
    try:
        url = f'{FINNHUB_BASE_URL}/stock/profile2?symbol={symbol}&token={FINNHUB_API_KEY}'
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        return data.get('name', 'N/A') 
    except requests.exceptions.RequestException as e:
        print(f"Error fetching profile for {symbol}: {e}")
        return 'N/A'


@app.route('/')
def home():
    """Renders the homepage with a list of stock data."""
    
    # 1. Get all stocks from the DB
    stocks_response = supabase.table('stocks').select('id, symbol, name').execute()
    stocks = stocks_response.data 
    
    # 2. Get all alerts from the DB
    alerts_response = supabase.table('alerts').select('*').execute()
    all_alerts = alerts_response.data
    
    # 3. Combine them and check prices
    for stock in stocks:
        # Get live price data
        stock_data = get_stock_quote(stock['symbol'])
        
        # Add price data to the stock object
        stock['current_price'] = stock_data.get('current_price')
        stock['price_change'] = stock_data.get('price_change')
        stock['percent_change'] = stock_data.get('percent_change')
        stock['opening_price'] = stock_data.get('opening_price')
        stock['high_price'] = stock_data.get('high_price')
        stock['low_price'] = stock_data.get('low_price')
        stock['error'] = stock_data.get('error')
        
        # Find all alerts for this specific stock
        stock_alerts = [alert for alert in all_alerts if alert['stock_id'] == stock['id']]
        
        # Check for triggers
        if not stock['error'] and stock['current_price'] is not None:
            current_price = stock['current_price']
            
            for alert in stock_alerts:
                is_triggered = False
                
                # Check High alerts
                if alert['alert_type'] == 'high' and current_price >= alert['target_price']:
                    is_triggered = True
                
                # Check Low alerts
                elif alert['alert_type'] == 'low' and current_price <= alert['target_price']:
                    is_triggered = True

                # If triggered and not already sent, send email!
                if is_triggered and alert['is_triggered'] is False:
                    print(f"Triggering {alert['alert_type']} alert for {stock['symbol']} to {alert['alert_email']}")
                    send_email_alert(
                        alert['alert_email'], stock['symbol'], stock['name'],
                        alert['alert_type'], current_price, alert['target_price']
                    )
                    # Mark as triggered in DB to prevent spam
                    supabase.table('alerts').update({'is_triggered': True}).eq('id', alert['id']).execute()
                    alert['is_triggered'] = True # Update for the template
        
        # Attach the list of alerts to the stock object
        stock['alerts'] = stock_alerts
            
    return render_template('index.html', stocks=stocks)


# --- MODIFIED: add_stock function ---
# This version includes the bug fix for searching by name
@app.route('/add_stock', methods=['POST'])
def add_stock():
    """Searches for a stock and adds it to the database."""
    search_term = request.form.get('new_stock_symbol')
    
    if not search_term:
        return redirect(url_for('home'))
        
    # Step 1: Search for the best match
    stock_data = search_for_stock(search_term)
    
    # Step 2: If a match is found, add it
    if stock_data:
        new_symbol = stock_data.get('symbol')
        # Use 'description' from search, it's often better than 'name' from profile
        company_name = stock_data.get('description') 
        
        try:
            # Check if symbol already exists
            existing = supabase.table('stocks').select('id').eq('symbol', new_symbol).execute()
            if not existing.data:
                # Add to database
                supabase.table('stocks').insert({
                    'symbol': new_symbol,
                    'name': company_name
                }).execute()
            else:
                flash(f"'{new_symbol}' is already in your list.")
                
        except Exception as e:
            print(f"Error adding stock: {e}")
            flash("Error adding stock to database.")
            
    # Step 3: If no match is found, send an error to the user
    else:
        flash(f"No stock found for '{search_term}'. Please try a different name or ticker.")

    return redirect(url_for('home'))


# --- NEW: Function to search for a stock symbol ---
def search_for_stock(search_term):
    """Uses Finnhub Search to find the best match for a search term."""
    try:
        url = f'{FINNHUB_BASE_URL}/search?q={search_term}&token={FINNHUB_API_KEY}'
        response = requests.get(url)
        response.raise_for_status() 
        data = response.json()
        
        # Check if 'result' exists and has items
        if data.get('result') and len(data['result']) > 0:
            # Return the first and best match
            return data['result'][0] 
        else:
            return None # No match found
            
    except requests.exceptions.RequestException as e:
        print(f"Error searching for stock {search_term}: {e}")
        return None


@app.route('/delete_stock', methods=['POST'])
def delete_stock():
    """Deletes a stock from the database."""
    stock_id_to_delete = request.form.get('stock_id')
    
    if stock_id_to_delete:
        try:
            # Cascade delete setting will automatically delete all related alerts
            supabase.table('stocks').delete().eq('id', stock_id_to_delete).execute()
        except Exception as e:
            print(f"Error deleting stock: {e}")
            
    return redirect(url_for('home'))


@app.route('/add_alert', methods=['POST'])
def add_alert():
    """Adds a new user alert to the alerts table."""
    stock_id = request.form.get('stock_id')
    email = request.form.get('alert_email')
    price = request.form.get('target_price')
    alert_type = request.form.get('alert_type') # 'high' or 'low'
    
    if stock_id and email and price and alert_type:
        try:
            supabase.table('alerts').insert({
                'stock_id': stock_id,
                'alert_email': email,
                'target_price': price,
                'alert_type': alert_type,
                'is_triggered': False # New alerts are always untriggered
            }).execute()
        except Exception as e:
            print(f"Error adding alert: {e}")
    
    return redirect(url_for('home'))


@app.route('/delete_alert', methods=['POST'])
def delete_alert():
    """Deletes a single alert from the database."""
    alert_id = request.form.get('alert_id')
    
    if alert_id:
        try:
            supabase.table('alerts').delete().eq('id', alert_id).execute()
        except Exception as e:
            print(f"Error deleting alert: {e}")
    
    return redirect(url_for('home'))


if __name__ == '__main__':
    app.run(debug=True)