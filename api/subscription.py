"""
Vercel API endpoint: Check subscription status
GET /api/subscription?telegram_id=123456789
"""
import os
import json
from datetime import datetime

# Vercel serverless handler
def handler(request):
    """Handle subscription check requests."""
    
    # Get telegram_id from query params
    telegram_id = request.args.get('telegram_id')
    
    if not telegram_id:
        return {
            'statusCode': 400,
            'body': json.dumps({'error': 'telegram_id required'})
        }
    
    try:
        telegram_id = int(telegram_id)
    except ValueError:
        return {
            'statusCode': 400,
            'body': json.dumps({'error': 'invalid telegram_id'})
        }
    
    # Connect to Supabase
    try:
        from supabase import create_client
        
        url = os.environ.get('SUPABASE_URL')
        key = os.environ.get('SUPABASE_SERVICE_KEY')
        
        if not url or not key:
            return {
                'statusCode': 500,
                'body': json.dumps({'error': 'Supabase not configured'})
            }
        
        client = create_client(url, key)
        
        # Get user
        result = client.table('users').select(
            'subscription_tier, subscription_expires_at'
        ).eq('telegram_id', telegram_id).execute()
        
        if not result.data:
            return {
                'statusCode': 200,
                'body': json.dumps({
                    'tier': 'free',
                    'active': False,
                    'expires_at': None,
                    'can_trade_live': False,
                    'can_use_custom': False
                })
            }
        
        user = result.data[0]
        tier = user.get('subscription_tier', 'free')
        expires_at = user.get('subscription_expires_at')
        
        # Check if active
        active = False
        if tier != 'free' and expires_at:
            try:
                expires = datetime.fromisoformat(expires_at.replace('Z', '+00:00'))
                active = datetime.now(expires.tzinfo) < expires
            except:
                pass
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'tier': tier if active else 'free',
                'active': active,
                'expires_at': expires_at,
                'can_trade_live': active and tier in ['basic', 'pro'],
                'can_use_custom': active and tier == 'pro'
            })
        }
        
    except Exception as e:
        return {
            'statusCode': 500,
            'body': json.dumps({'error': str(e)})
        }


# For Vercel Python runtime
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

class RequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        # Parse query string
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        
        class MockRequest:
            args = {k: v[0] for k, v in query.items()}
        
        result = handler(MockRequest())
        
        self.send_response(result.get('statusCode', 200))
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(result.get('body', '{}').encode())
