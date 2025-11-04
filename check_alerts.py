import os
import requests
from dotenv import load_dotenv
from supabase import create_client, Client
import brevo_python
from brevo_python.rest import ApiException
from brevo_python.models.send_smtp_email import SendSmtpEmail

# Load Environment
load_dotenv()

FINNHUB_API_KEY = os.getenv('FINNHUB_API_KEY')
FINNHUB_BASE_URL = 'https://finnhub.io/api/v1'
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
BREVO_API_KEY = os.getenv('BREVO_API_KEY')
BREVO_SENDER = os.getenv('BREVO_SENDER')

# Configure Brevo API
configuration = brevo_python.Configuration()
configuration.api_key['api-key'] = BREVO_API_KEY
api_instance = brevo_python.TransactionalEmailsApi(brevo_python.ApiClient(configuration))

# Fetch Stock Quote Function
def get_stock_quote(symbol):
    """Fetches stock quote data from Finnhub API."""
    try:
        url = f'{FINNHUB_BASE_URL}/quote?symbol={symbol}&token={FINNHUB_API_KEY}'
        response = requests.get(url)
        response.raise_for_status() 
        data = response.json()
        if data.get('c') == 0 and data.get('h') == 0:
            return {'symbol': symbol, 'error': 'No valid price data found for ticker.'}
        return {'symbol': symbol, 'current_price': data.get('c')}
    except requests.exceptions.RequestException as e:
        print(f"Error fetching quote for {symbol}: {e}")
        return {'symbol': symbol, 'error': 'Failed to fetch quote'}

def send_email_alert(target_email, symbol, name, alert_type, current_price, target_price):
    """Builds and sends an HTML email alert using the Brevo API."""
    if not BREVO_API_KEY or not BREVO_SENDER or not target_email:
        print(f"Skipping email for {symbol}: Missing Brevo keys or target email.")
        return

    if alert_type == 'high':
        subject = f"✅ High Price Alert for {symbol}!"
        color, alert_text = "#4CAF50", "hit high target"
    else:
        subject = f"🔻 Low Price Alert for {symbol}!"
        color, alert_text = "#dc3545", "hit low target"
        
    html_content = f"""
    <html><body><div style="font-family: Arial, sans-serif; max-width: 600px; margin: auto; padding: 20px; border: 1px solid #ddd; border-radius: 10px;">
      <h2 style="color: #333; text-align: center;">Many As Penny Alert!</h2>
      <h3 style="color: {color}; text-align: center;">{symbol} ({name}) {alert_text}</h3>
      <p>This is an automated alert to let you know that <strong>{symbol}</strong> has reached a price of <strong>${current_price:,.2f}</strong>.</p>
      <div style="background-color: #f9f9f9; padding: 15px; border-radius: 5px; text-align: center;">
        <p><strong>Target Price:</strong> ${target_price:,.2f}</p>
        <p style="color: {color};"><strong>Current Price:</strong> ${current_price:,.2f}</p>
      </div></div></body></html>
    """
    
    send_smtp_email = SendSmtpEmail(
        to=[{"email": target_email}],
        sender={"email": BREVO_SENDER, "name": "MAP Alert"},
        subject=subject,
        html_content=html_content
    )
    
    try:
        api_response = api_instance.send_transac_email(send_smtp_email)
        print(f"Email sent via Brevo API to {target_email}. Message ID: {api_response.message_id}")
    except ApiException as e:
        print(f"Error: Unable to send Brevo email. {e}")

# Check Alerts Function
def check_all_alerts():
    """The main function for the Cron Job."""
    print("Cron job started: Checking for triggered alerts...")
    
    response = supabase.table('alerts').select('*, stocks(symbol, name)').eq('is_triggered', False).execute()
    alerts = response.data
    
    if not alerts:
        print("No active alerts to check. Job finished.")
        return
        
    print(f"Found {len(alerts)} active alerts to check.")
    
    for alert in alerts:
        stock_info = alert.get('stocks')
        if not stock_info:
            continue 

        symbol = stock_info['symbol']
        name = stock_info['name']
        
        quote = get_stock_quote(symbol)
        if quote.get('error') or quote.get('current_price') is None:
            continue 

        current_price = quote['current_price']
        is_triggered = False

        if alert['alert_type'] == 'high' and current_price >= alert['target_price']:
            is_triggered = True
        elif alert['alert_type'] == 'low' and current_price <= alert['target_price']:
            is_triggered = True
            
        if is_triggered:
            print(f"TRIGGERED: {symbol} at ${current_price}. Target was {alert['alert_type']} ${alert['target_price']}. Sending email...")
            
            send_email_alert(
                alert['alert_email'], symbol, name,
                alert['alert_type'], current_price, alert['target_price']
            )
            
            supabase.table('alerts').update({'is_triggered': True}).eq('id', alert['id']).execute()

    print("Cron job finished.")

if __name__ == '__main__':
    check_all_alerts()