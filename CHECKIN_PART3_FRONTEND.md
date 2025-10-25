# CHECK-IN FLOW OVERHAUL - PART 3: FRONTEND

## 📄 Templates

### Template 1: checkin_step1.html
```html
{% extends 'base.html' %}
{% block content %}
<div class="checkin-container">
    <div class="progress-bar">
        <div class="step active">1</div>
        <div class="step">2</div>
        <div class="step">3</div>
        <div class="step">4</div>
    </div>
    
    <h1>🏠 Welcome to PickARooms</h1>
    <p>Enter your booking reference to check in</p>
    
    <form method="POST" class="checkin-form">
        {% csrf_token %}
        <input type="tel" name="booking_ref" id="booking_ref" 
               placeholder="1234567890" inputmode="numeric" 
               pattern="[0-9]*" required minlength="10" maxlength="10">
        
        <button type="submit" id="continue-btn" disabled>Continue →</button>
    </form>
    
    <details>
        <summary>❓ Where's my booking reference?</summary>
        <p>Check your Booking.com confirmation email...</p>
    </details>
</div>
{% endblock %}
```

### Template 2: checkin_step2.html
```html
{% extends 'base.html' %}
{% block content %}
<div class="checkin-container">
    <div class="progress-bar">
        <div class="step completed">✓</div>
        <div class="step active">2</div>
        <div class="step">3</div>
        <div class="step">4</div>
    </div>
    
    <h1>👤 Your Details</h1>
    
    <form method="POST" class="checkin-form">
        {% csrf_token %}
        
        <label>Full Name *</label>
        <input type="text" name="full_name" required>
        
        <label>Phone Number *</label>
        <input type="tel" name="phone_number" inputmode="tel" required 
               placeholder="+44 7539 029629">
        
        <label>Email (Optional)</label>
        <input type="email" name="email" inputmode="email">
        
        <button type="submit">Continue →</button>
    </form>
    
    <a href="{% url 'checkin' %}" class="back-btn">← Back</a>
</div>
{% endblock %}
```

### Template 3: checkin_step3.html
```html
{% extends 'base.html' %}
{% block content %}
<div class="checkin-container">
    <div class="progress-bar">
        <div class="step completed">✓</div>
        <div class="step completed">✓</div>
        <div class="step active">3</div>
        <div class="step">4</div>
    </div>
    
    <h1>🚗 Parking Information</h1>
    <p>Are you arriving by car?</p>
    
    <form method="POST" class="checkin-form">
        {% csrf_token %}
        
        <div class="radio-group">
            <label>
                <input type="radio" name="has_car" value="yes" id="car-yes">
                Yes, I'm driving
            </label>
            <label>
                <input type="radio" name="has_car" value="no" id="car-no">
                No, other transport
            </label>
        </div>
        
        <div id="car-details" style="display: none;">
            <label>Car Registration</label>
            <input type="text" name="car_registration" id="car_reg" 
                   placeholder="AB12 CDE" maxlength="10">
            
            <div class="parking-info">
                <h3>📍 Parking Instructions</h3>
                <p>• Park in front of building</p>
                <p>• Free on-street parking</p>
                <p>• No permit needed</p>
            </div>
        </div>
        
        <button type="submit">Continue →</button>
    </form>
    
    <a href="{% url 'checkin_details' %}" class="back-btn">← Back</a>
</div>

<script>
document.querySelectorAll('input[name="has_car"]').forEach(radio => {
    radio.addEventListener('change', function() {
        document.getElementById('car-details').style.display = 
            this.value === 'yes' ? 'block' : 'none';
    });
});
</script>
{% endblock %}
```

### Template 4: checkin_step4.html
```html
{% extends 'base.html' %}
{% block content %}
<div class="checkin-container">
    <div class="progress-bar">
        <div class="step completed">✓</div>
        <div class="step completed">✓</div>
        <div class="step completed">✓</div>
        <div class="step active">4</div>
    </div>
    
    <h1>✅ Almost There!</h1>
    <p>Please confirm your details:</p>
    
    <div class="summary-box">
        <p><strong>Name:</strong> {{ flow_data.full_name }}</p>
        <p><strong>Phone:</strong> {{ flow_data.phone_number }}</p>
        {% if flow_data.email %}
        <p><strong>Email:</strong> {{ flow_data.email }}</p>
        {% endif %}
        <p><strong>Room:</strong> {{ reservation.room.name }}</p>
        {% if flow_data.car_registration %}
        <p><strong>Car:</strong> {{ flow_data.car_registration }}</p>
        {% endif %}
    </div>
    
    <form method="POST" class="checkin-form">
        {% csrf_token %}
        <button type="submit" id="confirm-btn">
            ✅ Confirm & Get My PIN
        </button>
    </form>
    
    <a href="{% url 'checkin_parking' %}" class="back-btn">← Back</a>
</div>
{% endblock %}
```

### Template 5: checkin_not_found.html
```html
{% extends 'base.html' %}
{% block content %}
<div class="checkin-container">
    <h1>❌ Booking Not Found</h1>
    <p>We couldn't find reservation <strong>{{ booking_ref }}</strong></p>
    
    <div class="help-box">
        <h3>Common issues:</h3>
        <ul>
            <li>Check your Booking.com confirmation email</li>
            <li>Make sure you're using the 10-digit reference</li>
            <li>Your check-in date may not be today</li>
        </ul>
    </div>
    
    <a href="{% url 'checkin' %}" class="btn-primary">Try Again</a>
    
    <div class="contact-box">
        <h3>Still having issues?</h3>
        <p>📞 +44 7539 029629</p>
        <p>📧 easybulb@gmail.com</p>
    </div>
</div>
{% endblock %}
```

### Template 6: checkin_error.html
```html
{% extends 'base.html' %}
{% block content %}
<div class="checkin-container">
    <h1>⚠️ Technical Issue</h1>
    <p>We couldn't generate your room PIN automatically.</p>
    
    <div class="error-box">
        <p>Booking: <strong>{{ booking_ref }}</strong></p>
        <p>Error: {{ error }}</p>
    </div>
    
    <div class="contact-box">
        <h3>Please contact us:</h3>
        <p>📞 <a href="tel:+447539029629">+44 7539 029629</a></p>
        <p>📧 easybulb@gmail.com</p>
        <p>💬 <a href="https://wa.me/447539029629">WhatsApp</a></p>
        <p>We'll get you checked in right away!</p>
    </div>
</div>
{% endblock %}
```

## 🎨 CSS (static/css/checkin_flow.css)

```css
.checkin-container {
    max-width: 500px;
    margin: 40px auto;
    padding: 20px;
}

.progress-bar {
    display: flex;
    justify-content: space-between;
    margin-bottom: 30px;
}

.step {
    width: 40px;
    height: 40px;
    border-radius: 50%;
    background: #e0e0e0;
    display: flex;
    align-items: center;
    justify-content: center;
    font-weight: bold;
}

.step.active {
    background: #667eea;
    color: white;
}

.step.completed {
    background: #28a745;
    color: white;
}

.checkin-form input, .checkin-form button {
    width: 100%;
    min-height: 50px;
    font-size: 16px;
    padding: 12px;
    margin-bottom: 15px;
    border-radius: 8px;
    border: 2px solid #ddd;
}

.checkin-form button {
    background: #667eea;
    color: white;
    border: none;
    cursor: pointer;
    font-weight: bold;
}

.checkin-form button:disabled {
    opacity: 0.5;
    cursor: not-allowed;
}

input.valid {
    border-color: #28a745;
    background: #f0fff4;
}

input.invalid {
    border-color: #dc3545;
    background: #fff5f5;
}

.back-btn {
    display: inline-block;
    margin-top: 20px;
    color: #667eea;
}

/* Mobile optimization */
@media (max-width: 768px) {
    .checkin-container {
        padding: 15px;
    }
}
```

## ⚡ JavaScript (static/js/checkin_flow.js)

```javascript
document.addEventListener('DOMContentLoaded', function() {
    // Page transition on form submit
    const form = document.querySelector('.checkin-form');
    if (form) {
        form.addEventListener('submit', function(e) {
            const btn = form.querySelector('button[type="submit"]');
            if (btn && !btn.disabled) {
                btn.disabled = true;
                btn.innerHTML = '<span class="spinner"></span> Loading...';
                document.body.classList.add('page-exit');
            }
        });
    }
    
    // Booking ref validation (Step 1)
    const bookingRef = document.getElementById('booking_ref');
    const continueBtn = document.getElementById('continue-btn');
    
    if (bookingRef && continueBtn) {
        bookingRef.addEventListener('input', function() {
            const value = this.value.trim();
            const isValid = /^\d{10}$/.test(value);
            
            this.classList.toggle('valid', isValid);
            this.classList.toggle('invalid', value.length > 0 && !isValid);
            continueBtn.disabled = !isValid;
        });
    }
    
    // Car reg auto-format (Step 3)
    const carReg = document.getElementById('car_reg');
    if (carReg) {
        carReg.addEventListener('input', function(e) {
            let value = e.target.value.toUpperCase().replace(/[^A-Z0-9]/g, '');
            if (value.length > 4) {
                value = value.slice(0, 4) + ' ' + value.slice(4, 7);
            }
            e.target.value = value.trim();
        });
    }
});

// Page enter animation
document.body.classList.add('page-enter');
```

## 📖 Read Next: PART 4 (Background PIN Generation)
