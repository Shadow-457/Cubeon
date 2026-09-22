/* ============================================================================
   Cubeon site - shared behaviour.

   Deliberately small: the mobile menu, the FAQ answers, a gentle reveal on
   scroll, a "this one's for your device" star on the right download, the
   global download counter, and the cookie banner (which only ever appears if
   something genuinely needs consent - the site sets no cookies, and its only
   outside request is the anonymous download-count total, which is why
   cookies.html / privacy.html can keep describing the site accurately).
   Every block quits quietly when the page has none of the elements it drives,
   and everything works with JavaScript switched off.
   ========================================================================== */
(function(){
  /* ---- mobile menu ---- */
  var toggle = document.getElementById('navToggle');
  var slots = document.getElementById('navSlots');
  if(toggle && slots){
    toggle.addEventListener('click', function(){
      var open = slots.classList.toggle('open');
      toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
    });
    slots.addEventListener('click', function(e){
      if(e.target && e.target.tagName === 'A') slots.classList.remove('open');
    });
    document.addEventListener('keydown', function(e){
      if(e.key === 'Escape' && slots.classList.contains('open')){
        slots.classList.remove('open');
        toggle.setAttribute('aria-expanded', 'false');
        toggle.focus();
      }
    });
  }

  /* ---- FAQ: one answer open at a time ---- */
  var questions = document.querySelectorAll('.q');
  if(questions.length){
    questions.forEach(function(q){
      var btn = q.querySelector('.q-a');
      if(!btn) return;
      btn.addEventListener('click', function(){
        var wasOpen = q.classList.contains('open');
        questions.forEach(function(other){
          other.classList.remove('open');
          var b = other.querySelector('.q-a');
          if(b) b.setAttribute('aria-expanded', 'false');
        });
        if(!wasOpen){
          q.classList.add('open');
          btn.setAttribute('aria-expanded', 'true');
        }
      });
    });
  }

  /* ---- a little life on scroll (skipped for reduced-motion users) ---- */
  var rises = document.querySelectorAll('.rise');
  var calm = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  if(rises.length){
    if(calm || !('IntersectionObserver' in window)){
      rises.forEach(function(el){ el.classList.add('in'); });
    } else {
      var io = new IntersectionObserver(function(entries){
        entries.forEach(function(en){
          if(en.isIntersecting){ en.target.classList.add('in'); io.unobserve(en.target); }
        });
      }, {threshold:0.12, rootMargin:'0px 0px -30px 0px'});
      rises.forEach(function(el){ io.observe(el); });
    }
  }

  /* ---- which download is for this device? Decoration only: every link is a
     plain anchor in the HTML, so nothing here is required to download. ----
     This also drives the landing page's one-pane-at-a-time hero: `html.js
     .pane` stays hidden until a pane carries `.on`, and the "Not your system?"
     buttons pick one. That logic lived in an inline <script> in index.html
     until 2026-09-22 - the same page that never loaded this file, which is why
     the landing page showed no download count and no cookie note. -------- */
  (function markSystem(){
    var ua = String((navigator.userAgentData && navigator.userAgentData.platform) ||
                    navigator.platform || navigator.userAgent || '').toLowerCase();
    var os = /android|iphone|ipad|ipod/.test(ua) ? ''
           : /mac/.test(ua) ? 'mac'
           : /windows|win32|win64/.test(ua) ? 'windows'
           : /linux|x11/.test(ua) ? 'linux' : '';

    document.querySelectorAll('[data-os]').forEach(function(el){
      if(el.getAttribute('data-os') === os) el.classList.add('rec');
    });

    var panes = document.querySelectorAll('.pane');
    var picks = document.querySelectorAll('[data-pick]');
    if(!panes.length) return;                 /* only the landing page has these */
    function show(which){
      panes.forEach(function(pane){
        pane.classList.toggle('on', pane.getAttribute('data-os') === which);
      });
      picks.forEach(function(button){
        button.setAttribute('aria-pressed',
          button.getAttribute('data-pick') === which ? 'true' : 'false');
      });
    }
    picks.forEach(function(button){
      button.addEventListener('click', function(){ show(button.getAttribute('data-pick')); });
    });
    show(os || 'windows');                    /* an unknown device still gets a button */
  })();

  /* ---- global "downloads" counter ---------------------------------------
     Every press of a real download button (`/windowsdownload` and the Linux
     trio) adds one to a SHARED total that every visitor sees, here and on
     every page: not a per-device figure, but the overall number of presses.

     The total lives at Abacus (github.com/JasonCameron/abacus), an
     open-source, cookie-free counter service. The only thing it ever
     receives is "add 1 to cubeon-site" - no cookie, no identifier, nothing
     tied to a person - which is what lets cookies.html and privacy.html
     keep their promises. `/get` reads the total for display; `/hit` adds
     one and returns the new value (keepalive lets the +1 survive the jump
     to the release file, which navigates away from this page). If the
     counter cannot be reached the line simply stays hidden - never a
     made-up number. ------------------------------------------------------ */
  (function downloadCount(){
    var counters = document.querySelectorAll('[data-download-count]');
    if(!counters.length || !window.fetch) return;
    var BASE = 'https://abacus.jasoncameron.dev';
    var NAMESPACE = 'cubeon-site';
    var KEY = 'downloads';
    /* Routes that hand over a file, mirroring the redirects in
       web/vercel.json - a test keeps the two lists equal. Links to the
       download PAGE are page views, not downloads. */
    var ROUTES = ['/windowsdownload', '/linuxdownload', '/linuxdeb', '/linuxsetup'];

    function paint(total){
      var label = new Intl.NumberFormat().format(total) +
        (total === 1 ? ' download so far' : ' downloads so far');
      counters.forEach(function(counter){
        counter.textContent = label;
        counter.hidden = false;
      });
    }
    /* Only a whole, non-negative number paints. Anything else (an error
       body, an HTML 404 page) hides the line. */
    function totalIn(data){
      return data && typeof data.value === 'number'
             && isFinite(data.value) && data.value >= 0 ? data.value : null;
    }
    function ask(action){
      return fetch(BASE + '/' + action + '/' + NAMESPACE + '/' + KEY, {
        headers: { 'Accept': 'application/json' },
        keepalive: action === 'hit'
      })
        .then(function(response){ return response.ok ? response.json() : null; })
        .then(totalIn)
        .catch(function(){ return null; });
    }
    function isDownload(anchor){
      var href = anchor.getAttribute('href') || '';
      return ROUTES.indexOf(href) !== -1 || ROUTES.indexOf(anchor.pathname) !== -1;
    }

    ask('get').then(function(total){
      if(total !== null) paint(total);      /* everyone sees the overall count */
    });

    document.addEventListener('click', function(event){
      var anchor = event.target && event.target.closest ? event.target.closest('a[href]') : null;
      if(!anchor || !isDownload(anchor)) return;
      ask('hit').then(function(total){
        if(total !== null) paint(total);    /* the fresh, shared total */
      });
    });
  })();

  /* ---- fun terms-acceptance checklist (terms.html only) ------------------
     Pure decoration on top of a plain link: with JS off, the button is just
     a link straight to the download page, so nothing here is required to
     use the site. With JS on, it gates the button on the three checkboxes
     and adds a little celebration before sending you on. ------------------ */
  (function acceptChecklist(){
    var card = document.getElementById('acceptCard');
    if(!card) return;
    var boxes = card.querySelectorAll('.accept-box');
    var btn = document.getElementById('acceptBtn');
    var hint = document.getElementById('acceptHint');
    var label = btn ? btn.querySelector('.accept-btn-label') : null;
    var confetti = btn ? btn.querySelector('.accept-confetti') : null;
    if(!boxes.length || !btn) return;

    function allChecked(){
      return Array.prototype.every.call(boxes, function(b){ return b.checked; });
    }
    function sync(){
      var done = allChecked();
      card.classList.toggle('all-checked', done);
      if(hint) hint.textContent = done
        ? "That's the deal - click through whenever you're ready."
        : "Check all three and this button turns into a launch pad.";
    }
    boxes.forEach(function(b){ b.addEventListener('change', sync); });
    sync();

    btn.addEventListener('click', function(e){
      if(!allChecked()){
        e.preventDefault();
        card.classList.remove('wiggle');
        void card.offsetWidth; /* restart the animation */
        card.classList.add('wiggle');
        if(hint) hint.textContent = 'Almost - three little boxes to go.';
        return;
      }
      e.preventDefault();
      if(label) label.textContent = 'Sealed! Off you go';
      if(confetti) confetti.style.display = 'inline';
      window.setTimeout(function(){ window.location.href = btn.getAttribute('href'); }, 550);
    });
  })();

  /* ---- small "no cookies" badge, bottom-right --------------------------
     Not a consent request (there's nothing to consent to) - just a quiet,
     persistent reassurance. Dismissible; the dismissal is remembered so it
     doesn't come back every visit. Runs on every page since it's injected
     here rather than pasted into each HTML file. ------------------------ */
  (function cookieNote(){
    var KEY = 'cubeon_cookie_note_dismissed';
    var dismissed = null;
    try { dismissed = localStorage.getItem(KEY); } catch (_) { dismissed = null; }
    if(dismissed) return;
    var el = document.createElement('div');
    el.className = 'cookie-note';
    el.setAttribute('role', 'status');
    el.innerHTML =
      '<p>No cookies here - never have been. <a href="cookies.html">Why</a></p>' +
      '<button type="button" aria-label="Dismiss">&times;</button>';
    document.body.appendChild(el);
    var closeBtn = el.querySelector('button');
    closeBtn.addEventListener('click', function(){
      try { localStorage.setItem(KEY, '1'); } catch (_) {}
      el.remove();
    });
  })();

  /* ---- cookie banner -------------------------------------------------------
     There is nothing to ask about today, so nothing renders and nothing is
     stored. If that ever changes, set window.CUBEON_CONSENT = { needsConsent:
     true } before this file loads and the banner appears - accept and reject
     side by side, nothing pre-ticked. See cookies.html.
     ------------------------------------------------------------------------ */
  (function cookieBanner(){
    var cfg = window.CUBEON_CONSENT || {};
    if(!cfg.needsConsent) return;
    var KEY = 'cubeon_consent_v1', stored = null;
    try { stored = localStorage.getItem(KEY); } catch (_) { stored = null; }
    if(stored) return;
    var el = document.createElement('div');
    el.className = 'consent';
    el.setAttribute('role', 'dialog');
    el.setAttribute('aria-label', 'Cookie choices');
    el.innerHTML =
      '<div class="wrap">' +
        '<div class="txt"><b>Cookies &amp; your choices</b>' +
        '<p>Cubeon sets no cookies today. If that ever changes, nothing extra runs until you say yes. Read the ' +
        '<a href="cookies.html">cookie page</a>.</p></div>' +
        '<div class="acts">' +
          '<button class="btn" type="button" data-consent="all">Accept all</button>' +
          '<button class="btn quiet" type="button" data-consent="none">Reject non-essential</button>' +
        '</div>' +
      '</div>';
    document.body.appendChild(el);
    var first = el.querySelector('[data-consent="all"]');
    if(first) first.focus();
    el.addEventListener('click', function(e){
      var b = e.target && e.target.closest ? e.target.closest('[data-consent]') : null;
      if(!b) return;
      try { localStorage.setItem(KEY, b.getAttribute('data-consent')); } catch (_) {}
      el.remove();
    });
  })();
})();
