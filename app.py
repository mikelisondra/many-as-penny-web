import os
import requests
from flask import Flask, render_template, request, redirect, url_for
from dotenv import load_dotenv
from supabase import create_client, Client

# IMPORTS for sending email
import smtplib
import ssl
from email.message import EmailMessage

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

# Get All Brevo Credentials
BREVO_SERVER = os.getenv('BREVO_SERVER')
BREVO_PORT = os.getenv('BREVO_PORT')
BREVO_USER = os.getenv('BREVO_USER') # Brevo SMTP login
BREVO_PASS = os.getenv('BREVO_PASS') # Brevo SMTP key
BREVO_SENDER = os.getenv('BREVO_SENDER') # Validated 'From' email


# Brevo Email Function
def send_email_alert(target_email, symbol, name, alert_type, current_price, target_price):
    """Builds and sends an HTML email alert using Brevo SMTP."""
    
    # Check for all the new variables
    if not BREVO_SERVER or not BREVO_PASS or not BREVO_USER or not BREVO_SENDER:
        print("Brevo keys not set in .env. Skipping email.")
        return

    if not target_email:
        print(f"No alert_email set for {symbol}. Skipping email.")
        return

    # Set dynamic content based on alert type
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
    
    # Create the email message object
    em = EmailMessage()
    # The 'From' address is the validated BREVO_SENDER
    em['From'] = BREVO_SENDER 
    em['To'] = target_email
    em['Subject'] = subject
    em.add_alternative(html_content, subtype='html') # Set the HTML content
    
    # Send the email via Brevo's SMTP server
    try:
        context = ssl.create_default_context()
        
        with smtplib.SMTP(BREVO_SERVER, int(BREVO_PORT)) as server:
            server.starttls(context=context) # Secure the connection
            # Login is done with BREVO_USER and BREVO_PASS
            server.login(BREVO_USER, BREVO_PASS) 
            # Email is sent from BREVO_SENDER to the target
            server.sendmail(BREVO_SENDER, target_email, em.as_string()) 
            
        print(f"Email sent via Brevo to {target_email}.")
        
    except Exception as e:
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


@app.route('/add_stock', methods=['POST'])
def add_stock():
    """Adds a new stock symbol AND name to the database."""
    new_symbol = request.form.get('new_stock_symbol')
    
    if new_symbol:
        new_symbol = new_symbol.strip().upper()
        company_name = get_stock_profile(new_symbol)
        try:
            supabase.table('stocks').insert({
                'symbol': new_symbol,
                'name': company_name
            }).execute()
        except Exception as e:
            print(f"Error adding stock: {e}")
    
    return redirect(url_for('home'))


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