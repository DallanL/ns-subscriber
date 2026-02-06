(function() {
    'use strict';

    if (window.ns_addon_initialized) {
        return;
    }
    window.ns_addon_initialized = true;

    /**
     * Netsapiens Subscription Registry Addon - Portal Injection
     * - CSS: Bootstrap 2.x
     * - JS: jQuery
     * - Backend: FastAPI
     */

    // CONFIGURATION
    var apiEndpoint = '{{ api_endpoint }}'; 
    var clientId = '{{ client_id }}';
    var redirectUri = '{{ redirect_uri }}';

    // GLOBAL STATE
    window.ns_health_count = 0;
    window.ns_last_health_check = 0;
    window.ns_was_inventory = false;
    window.ns_observer_timeout = null;

    // BADGE LOGIC
    function updateBadgeState() {
        var count = window.ns_health_count;
        var $mainBadge = $('#ns-sub-badge');
        var $tabBadge = $('#ns-sub-tab-badge');

        if (count <= 0) {
            if ($mainBadge.length > 0 || $tabBadge.length > 0) {
                $mainBadge.remove();
                $tabBadge.remove();
            }
            return;
        }

        var $invNav = $('#nav-inventory');
        if ($invNav.length === 0) return;

        var isInventoryActive = $invNav.hasClass('nav-link-current') || $invNav.hasClass('active');
        
        // 1. Main Nav Badge
        if (!isInventoryActive) {
            if ($tabBadge.length > 0) $tabBadge.hide();
            
            if ($mainBadge.length === 0) {
                $mainBadge = $('<span id="ns-sub-badge" class="badge badge-important"></span>');
                $mainBadge.css({
                    'position': 'absolute', 'top': '-10px', 'right': '0', 'padding': '5px 9px',
                    'border-radius': '12px', 'font-size': '14px', 'display': 'none'
                });
                var $link = $invNav.find('a');
                var $target = $link.length > 0 ? $link : $invNav;
                if ($target.css('position') === 'static') $target.css('position', 'relative');
                $target.append($mainBadge);
            }
            
            if ($mainBadge.text() !== String(count)) {
                $mainBadge.text(count);
            }
            if (!$mainBadge.is(':visible')) {
                $mainBadge.show();
            }
        } else {
            if ($mainBadge.length > 0) $mainBadge.hide();
            
            // 2. Sub-Tab Badge
            var $subTab = $('#tab_ns_subscriptions a');
            if ($subTab.length > 0) {
                if ($tabBadge.length === 0) {
                    $tabBadge = $('<span id="ns-sub-tab-badge" class="badge badge-important"></span>');
                    $tabBadge.css({
                        'position': 'absolute', 'top': '-8px', 'right': '-7px',
                        'padding': '2px 4px', 'border-radius': '9px', 'font-size': '11.844px',
                        'font-weight': 'bold', 'line-height': '14px', 'color': '#fff',
                        'text-shadow': '0 -1px 0 rgba(0, 0, 0, 0.25)', 'white-space': 'nowrap',
                        'display': 'none'
                    });
                    if ($subTab.css('position') === 'static') $subTab.css('position', 'relative');
                    $subTab.append($tabBadge);
                }
                
                if ($tabBadge.text() !== String(count)) {
                    $tabBadge.text(count);
                }
                if (!$tabBadge.is(':visible')) {
                    $tabBadge.show();
                }
            }
        }
    }

    // AUTH HELPERS
    function startAuthFlow(domain, user, item) {
        var token = localStorage.getItem("ns_t");
        
        var stateObj = {
            domain: domain,
            user: user,
            redirect_uri: redirectUri
        };
        
        var stateStr = btoa(JSON.stringify(stateObj)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
        
        var authBase = ''; // We will construct this from a known base if needed, or assume same domain
        // Actually, startAuthFlow previously took apiUrl from portal.
        // We should probably still use the portal's server_name to find the NS API Authorize endpoint
        var portalApiUrl = typeof server_name !== 'undefined' ? server_name : window.location.hostname;
        var authBase = portalApiUrl.split('/ns-api/')[0];
        if (authBase === portalApiUrl) authBase = ''; 
        
        var authUrl = authBase + '/ns-api/authorize/index';
        
        var fullUrl = authUrl + 
            '?client_id=' + encodeURIComponent(clientId) + 
            '&redirect_uri=' + encodeURIComponent(redirectUri) + 
            '&response_type=code' + 
            '&state=' + encodeURIComponent(stateStr);
            
        var width = 500;
        var height = 600;
        var left = (screen.width/2)-(width/2);
        var top = (screen.height/2)-(height/2);
        
        var popup = window.open(fullUrl, "ns_auth_popup", "width="+width+",height="+height+",top="+top+",left="+left);
        
        function receiveMessage(event) {
            if (event.data === "ns_auth_success") {
                // Auth done!
                if (popup) popup.close();
                // Open modal with item
                openEditModal(item);
                window.removeEventListener("message", receiveMessage);
            }
        }
        window.addEventListener("message", receiveMessage, false);
    }

    function checkAndOpenNewSubModal(item) {
        var token = localStorage.getItem("ns_t");
        
        // Check if we need auth
        $.ajax({
            url: apiEndpoint.replace('/subscriptions', '/auth/check'),
            method: 'GET',
            headers: { 'Authorization': 'Bearer ' + token },
            success: function(data) {
                if (data.has_auth) {
                    openEditModal(item);
                } else {
                    if (confirm("To manage background subscriptions, you need to connect your Netsapiens account. Connect now?")) {
                        // Use domain/user from backend response if available, else fallback
                        var domain = data.domain || (typeof current_domain !== 'undefined' ? current_domain : '');
                        var user = data.user || (typeof my_extension !== 'undefined' ? my_extension : '');
                        
                        startAuthFlow(domain, user, item);
                    }
                }
            },
            error: function(err) {
                alert("Failed to check auth status: " + err.statusText);
            }
        });
    }

    // HELPERS
    function showHealthWarning(message) {
        if ($('#ns_health_warning').length > 0) {
            $('#ns_health_warning_text').text(message);
            return;
        }

        var $warning = $('<div id="ns_health_warning" class="alert alert-error">')
            .css({ 'margin': '0', 'position': 'relative', 'border-radius': '0', 'border-left': 'none', 'border-right': 'none' });
        
        var $closeBtn = $('<button type="button" class="close" data-dismiss="alert">×</button>');
        var $content = $('<div style="padding: 5px 20px;">');
        var $strong = $('<strong>Maintenance Warning:</strong> ');
        var $text = $('<span id="ns_health_warning_text">').text(message);
        var $link = $('<a href="javascript:void(0);" id="btn_goto_subs" style="text-decoration: underline; margin-left: 10px;">View Subscriptions</a>');

        $content.append($strong, $text, ' ', $link);
        $warning.append($closeBtn, $content);

        // Insert into the header area
        $('#header').prepend($warning);

        $('#btn_goto_subs').on('click', function() {
            $('#tab_ns_subscriptions a').trigger('click');
        });
    }

    function checkSubscriptionHealth() {
        var now = new Date().getTime();
        if (now - window.ns_last_health_check < 5000) { // Max once every 5 seconds
            return;
        }
        window.ns_last_health_check = now;

        // Only run health check if we are in the Inventory area or the Subscriptions tab is visible
        var $invNav = $('#nav-inventory');
        var isInventoryActive = $invNav.hasClass('nav-link-current') || $invNav.hasClass('active');
        var isSubTabVisible = $('#tab_ns_subscriptions').length > 0 && $('#tab_ns_subscriptions').is(':visible');

        if (!isInventoryActive && !isSubTabVisible) {
            console.debug("Skipping health check: Not in Inventory/Subscriptions area.");
            return;
        }

        var token = localStorage.getItem("ns_t");
        var statusEndpoint = apiEndpoint + "/status";

        $.ajax({
            url: statusEndpoint,
            method: 'GET',
            headers: {
                'Authorization': 'Bearer ' + token
            },
            success: function(data) {
                if (data.status === 'unhealthy') {
                    showHealthWarning(data.message);
                    window.ns_health_count = data.count;
                } else {
                    $('#ns_health_warning').remove();
                    window.ns_health_count = 0;
                }
                updateBadgeState();
            },
            error: function(err) {
                console.error("Health check failed:", err);
            }
        });
    }

    function archiveSubscription(id, token) {
        if (!confirm("Are you sure you want to archive this subscription?")) return;
        
        if (!id) {
            alert("Cannot archive unmanaged subscription yet.");
            return;
        }

        $.ajax({
            url: apiEndpoint + '/' + id,
            method: 'DELETE',
            headers: {
                'Authorization': 'Bearer ' + token
            },
            success: function() {
                loadSubscriptionData();
            },
            error: function(err) {
                alert("Failed to archive: " + err.statusText);
            }
        });
    }

    function adoptSubscription(item, token) {
        var payload = {
            user: item.user,
            subscription_model: item.subscription_model,
            post_url: item.post_url,
            description: "Adopted from PBX"
        };

        $.ajax({
            url: apiEndpoint + '/adopt',
            method: 'POST',
            contentType: 'application/json',
            headers: { 'Authorization': 'Bearer ' + token },
            data: JSON.stringify(payload),
            success: function() {
                loadSubscriptionData();
            },
            error: function(err) {
                alert("Failed to adopt: " + err.statusText);
            }
        });
    }

    function openEditModal(item) {
        $('#modal_alert_container').empty();
        $('#form_new_subscription')[0].reset();
        
        // Populate fields
        $('#sub_id').val(item ? (item.id || '') : ''); 
        if (item) {
            $('#sub_user').val(item.user).prop('disabled', true);
            $('#sub_model').val(item.subscription_model).prop('disabled', true);
            $('#sub_url').val(item.post_url);
            $('#sub_desc').val(item.description || '');
            $('#modal_new_subscription h3').text(item.id ? 'Edit Subscription' : 'Adopt & Edit Subscription');
        } else {
            $('#sub_user').prop('disabled', false);
            $('#sub_model').prop('disabled', false);
            $('#modal_new_subscription h3').text('New Subscription');
        }
        
        $('#modal_new_subscription').modal('show');
    }

    // DATA FETCHER & RENDERER
    function loadSubscriptionData() {
        if ($('#subscription_container').is(':visible') && $('#subscription_container').children().length > 1) {
             // Already has data and visible, skip unless explicit refresh
             // (Spinner + table is more than 1 child)
        }

        var token = localStorage.getItem("ns_t");
        
        if (typeof current_domain === 'undefined' || !current_domain) {
            $('#subscription_container').html('<div class="alert alert-danger" style="margin:20px;">Error: "current_domain" is not defined.</div>');
            return;
        }

        // Show Loading
        $('#subscription_container').html(
            '<div style="padding: 40px; text-align: center; color: #666;">' +
            '<i class="fa fa-spinner fa-spin fa-2x fa-fw"></i>' +
            '<div style="margin-top: 10px;">Loading Subscriptions...</div>' +
            '</div>'
        );

        $.ajax({
            url: apiEndpoint + "/list",
            method: 'GET',
            headers: {
                'Authorization': 'Bearer ' + token
            },
            success: function(data) {
                window.ns_subs_data = data; // Store for lookup
                
                var $container = $('#subscription_container').empty();
                var $table = $('<table class="table table-striped table-bordered table-condensed">');
                var $thead = $('<thead><tr><th>Status</th><th>User</th><th>Model</th><th>URL</th><th>Description</th><th>Actions</th></tr></thead>');
                var $tbody = $('<tbody>');
                
                if (!data || data.length === 0) {
                    $tbody.append('<tr><td colspan="6" style="text-align:center;">No subscriptions found.</td></tr>');
                } else {
                    $.each(data, function(i, item) {
                        var statusLabel = 'label-success';
                        var statusText = item.status;
                        
                        if (item.maintenance_status === 'failed') {
                            statusLabel = 'label-important';
                            statusText = 'Maint. Failed';
                        } else if (item.status === 'archived') {
                            statusLabel = 'label-inverse'; 
                        } else if (item.source === 'pbx') {
                            statusLabel = 'label-warning';
                            statusText = 'Unmanaged';
                        } else if (item.status === 'expired') {
                            statusLabel = 'label-important';
                        }

                        var $tr = $('<tr>');
                        if (item.maintenance_message) {
                            $tr.attr('title', item.maintenance_message);
                        }

                        $tr.append($('<td>').append($('<span class="label ' + statusLabel + '">').text(statusText)));
                        $tr.append($('<td>').text(item.user || ''));
                        $tr.append($('<td>').text(item.subscription_model || ''));
                        
                        var $urlDiv = $('<div style="max-width:400px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">')
                            .text(item.post_url || '')
                            .attr('title', item.post_url || '');
                        $tr.append($('<td>').append($urlDiv));
                        
                        $tr.append($('<td>').text(item.description || ''));
                        
                        var $actions = $('<td>');
                        if (item.status !== 'archived' && item.id) {
                             $actions.append($('<button class="btn btn-mini btn-primary btn-edit" title="Edit"><i class="icon-edit icon-white"></i></button>').data('id', item.id), ' ');
                             $actions.append($('<button class="btn btn-mini btn-danger btn-archive" title="Archive"><i class="icon-trash icon-white"></i></button>').data('id', item.id));
                        } else if (!item.id) {
                            $actions.append($('<button class="btn btn-mini btn-success btn-adopt" title="Adopt"><i class="icon-download icon-white"></i></button>').data('index', i), ' ');
                            $actions.append($('<button class="btn btn-mini btn-primary btn-edit-unmanaged" title="Edit & Adopt"><i class="icon-edit icon-white"></i></button>').data('index', i));
                        }
                        
                        $tr.append($actions);
                        $tbody.append($tr);
                    });
                }
                
                $table.append($thead, $tbody);
                $container.append($table);
                
                // Wire buttons
                $('.btn-archive').on('click', function() {
                    var id = $(this).data('id');
                    archiveSubscription(id, token);
                });

                $('.btn-adopt').on('click', function() {
                    var index = $(this).data('index');
                    var item = window.ns_subs_data[index];
                    adoptSubscription(item, token);
                });

                $('.btn-edit').on('click', function() {
                    var id = $(this).data('id');
                    var item = window.ns_subs_data.find(function(s) { return s.id === id; });
                    checkAndOpenNewSubModal(item);
                });

                $('.btn-edit-unmanaged').on('click', function() {
                    var index = $(this).data('index');
                    var item = window.ns_subs_data[index];
                    checkAndOpenNewSubModal(item);
                });
            },
            error: function(err) {
                var msg = (err.responseJSON && err.responseJSON.detail) ? err.responseJSON.detail : err.statusText;
                $('#subscription_container').html(
                    '<div class="alert alert-danger" style="margin:20px;">' +
                    '<strong>API Error:</strong> ' + msg + 
                    '</div>'
                );
                console.error("Subscription API Error:", err);
            }
        });
    }

    // --- MAIN INJECTION LOGIC ---
    function initSubscriptionTab() {
        if ($('#tab_ns_subscriptions').length > 0) return;

        var $phoneTab = $('.nav-tabs a:contains("Phone Numbers")');
        var $nativePanel = $('.inventory-panel-main');

        if ($phoneTab.length > 0 && $nativePanel.length > 0) {

            var elementsToHide = '.inventory-panel-main, .alert:not(.alert-info), .action-container-left, .action-container-right';
            var $navContainer = $phoneTab.closest('ul');
            var $parentContainer = $nativePanel.parent();

            // Add Tab
            $navContainer.append(
                '<li id="tab_ns_subscriptions">' +
                    '<a href="javascript:void(0);" style="cursor: pointer;"><i class="icon-refresh"></i> Subscriptions</a>' +
                '</li>'
            );

            // Add Content Container
            var newContentHTML =
                '<div id="content_ns_subscriptions" style="display:none; padding: 20px; background: #fff; height: 100%; position: relative; overflow-y: auto;">' +
                    '<div style="margin-bottom: 15px; text-align: right;">' +
                        '<button class="btn btn-primary" id="btn_new_sub"><i class="icon-plus icon-white"></i> New Subscription</button> ' +
                        '<button class="btn" id="btn_refresh_sub"><i class="icon-repeat"></i> Refresh</button>' +
                    '</div>' +
                    '<div id="subscription_container" style="width: 100%; border: 1px solid #ddd; background: #fff; min-height: 400px; border-radius: 4px;"></div>' +
                '</div>';

            $parentContainer.append(newContentHTML);
            
            // Add CSS fixes for Modal visibility (some portal versions hide these by default)
            if ($('#style_ns_modal_fix').length === 0) {
                $('head').append(
                    '<style id="style_ns_modal_fix">' +
                    '#modal_new_subscription .modal-header, ' +
                    '#modal_new_subscription .modal-body, ' +
                    '#modal_new_subscription .modal-footer { ' +
                    '    display: block !important; ' +
                    '}' +
                    '.ui-autocomplete { z-index: 100005 !important; }' +
                    '</style>'
                );
            }
            
            // Add Modal HTML (Append to body to avoid overflow/z-index issues)
            if ($('#modal_new_subscription').length === 0) {
                var modalHTML = 
                    '<div id="modal_new_subscription" class="modal hide fade" tabindex="-1" role="dialog" aria-hidden="true" style="width: 600px; margin-left: -300px; background-color: #fff; position: fixed; top: 10%; left: 50%; z-index: 99999; height: auto; display: none;">' +
                        '<div class="modal-header">' +
                        '<button type="button" class="close" data-dismiss="modal" aria-hidden="true">×</button>' +
                        '<h3>New Subscription</h3>' +
                    '</div>' +
                    '<div class="modal-body">' +
                        '<form class="form-horizontal" id="form_new_subscription">' +
                            '<input type="hidden" id="sub_id">' +
                            '<div class="control-group">' +
                                '<label class="control-label" for="sub_user">User</label>' +
                                '<div class="controls">' +
                                    '<input type="text" id="sub_user" placeholder="Extension (e.g. 1001)" class="input-medium" autocomplete="off">' +
                                    '<span class="help-inline">Type to search</span>' +
                                '</div>' +
                            '</div>' +
                            '<div class="control-group">' +
                                '<label class="control-label" for="sub_model">Model</label>' +
                                '<div class="controls">' +
                                    '<select id="sub_model" class="input-medium">' +
                                        '<option value="call">Call</option>' +
                                        '<option value="message">Message</option>' +
                                        '<option value="contact">Contact</option>' +
                                        '<option value="presence">Presence</option>' +
                                        '<option value="account">Account</option>' +
                                        '<option value="call-queue">Call Queue</option>' +
                                        '<option value="conference">Conference</option>' +
                                        '<option value="device">Device</option>' +
                                        '<option value="meeting">Meeting</option>' +
                                        '<option value="sms">SMS</option>' +
                                        '<option value="voicemail">Voicemail</option>' +
                                    '</select>' +
                                '</div>' +
                            '</div>' +
                            '<div class="control-group">' +
                                '<label class="control-label" for="sub_url">Post URL</label>' +
                                '<div class="controls">' +
                                    '<input type="text" id="sub_url" placeholder="https://..." class="input-xlarge">' +
                                '</div>' +
                            '</div>' +
                            '<div class="control-group">' +
                                '<label class="control-label" for="sub_desc">Description</label>' +
                                '<div class="controls">' +
                                    '<input type="text" id="sub_desc" placeholder="Optional note" class="input-xlarge">' +
                                '</div>' +
                            '</div>' +
                        '</form>' +
                        '<div id="modal_alert_container"></div>' +
                    '</div>' +
                    '<div class="modal-footer">' +
                        '<button class="btn" data-dismiss="modal" aria-hidden="true">Close</button>' +
                        '<button class="btn btn-primary" id="btn_save_subscription">Save changes</button>' +
                    '</div>' +
                '</div>';
            
                $('body').append(modalHTML);
            }

            // --- EVENT HANDLERS ---

            $('#tab_ns_subscriptions a').on('click', function(e) {
                e.preventDefault();
                e.stopPropagation();
                
                $navContainer.find('li').removeClass('active nav-link-current');
                $('#tab_ns_subscriptions').addClass('active');
                $(elementsToHide).hide();
                $('#content_ns_subscriptions').show();
                
                loadSubscriptionData();
            });

            $navContainer.find('li').not('#tab_ns_subscriptions').find('a').on('click', function() {
                $('#tab_ns_subscriptions').removeClass('active');
                $('#content_ns_subscriptions').hide();
                $(elementsToHide).css('display', '');
            });
            
            $('#btn_refresh_sub').on('click', function() {
                loadSubscriptionData();
            });
            
            // New Subscription Modal Logic
            $('#btn_new_sub').on('click', function() {
                checkAndOpenNewSubModal(null);
                
                // Initialize Autocomplete if not already
                if (!$("#sub_user").hasClass("ui-autocomplete-input")) {
                    var localSource = [];
                    // Try to scrape existing users from portal DOM
                    var $avail = $('#available_users');
                    if ($avail.length > 0) {
                        $avail.find('option').each(function() {
                            var ext = $(this).data('extension') || $(this).val().split(' ')[0];
                            localSource.push({
                                label: $(this).text() || $(this).val(),
                                value: ext
                            });
                        });
                    }

                    $("#sub_user").autocomplete({
                        delay: 400, // Debounce typing
                        source: function(request, response) {
                            // 1. Try Local Search first
                            if (localSource.length > 0) {
                                var matcher = new RegExp($.ui.autocomplete.escapeRegex(request.term), "i");
                                var results = $.grep(localSource, function(value) {
                                    return matcher.test(value.label) || matcher.test(value.value);
                                });
                                if (results.length > 0) {
                                    response(results);
                                    return;
                                }
                            }
                            
                            // 2. Fallback to API
                            var token = localStorage.getItem("ns_t");
                            var searchEndpoint = apiEndpoint.replace('/subscriptions', '/users/search');
                            
                            $.ajax({
                                url: searchEndpoint,
                                dataType: "json",
                                headers: { 'Authorization': 'Bearer ' + token },
                                data: {
                                    q: request.term
                                },
                                success: function(data) {
                                    response($.map(data, function(item) {
                                        return {
                                            label: item.user + " (" + (item['name-first-name'] || '') + " " + (item['name-last-name'] || '') + ")",
                                            value: item.user
                                        };
                                    }));
                                },
                                error: function() {
                                    response([]);
                                }
                            });
                        },
                        minLength: 0 // Allow showing all if empty
                    }).focus(function() {
                        $(this).autocomplete("search", $(this).val());
                    });
                }
            });
            
            $('#btn_save_subscription').on('click', function() {
                var id = $('#sub_id').val();
                var user = $('#sub_user').val();
                var model = $('#sub_model').val();
                var url = $('#sub_url').val();
                var desc = $('#sub_desc').val();
                
                if (!user || !url) {
                    $('#modal_alert_container').html('<div class="alert alert-error">User and Post URL are required.</div>');
                    return;
                }
                
                var token = localStorage.getItem("ns_t");
                
                var payload = {
                    user: user,
                    subscription_model: model,
                    post_url: url,
                    description: desc
                };
                
                $(this).prop('disabled', true).text('Saving...');
                
                var method = id ? 'PUT' : 'POST';
                var endpoint = id ? (apiEndpoint + '/' + id) : (apiEndpoint + '/adopt');
                
                $.ajax({
                    url: endpoint,
                    method: method,
                    contentType: 'application/json',
                    headers: { 'Authorization': 'Bearer ' + token },
                    data: JSON.stringify(payload),
                    success: function() {
                        $('#modal_new_subscription').modal('hide');
                        $('#btn_save_subscription').prop('disabled', false).text('Save changes');
                        loadSubscriptionData();
                    },
                    error: function(err) {
                        $('#btn_save_subscription').prop('disabled', false).text('Save changes');
                        var msg = (err.responseJSON && err.responseJSON.detail) ? err.responseJSON.detail : err.statusText;
                        if (typeof msg === 'object') msg = JSON.stringify(msg); // Handle validation error list
                        $('#modal_alert_container').html('<div class="alert alert-error"><strong>Error:</strong> ' + msg + '</div>');
                    }
                });
            });
        }
        // Removed checkSubscriptionHealth from here to avoid spamming
    }

    initSubscriptionTab();
    
    function scheduleNextHealthCheck() {
        setTimeout(function() {
            checkSubscriptionHealth();
            scheduleNextHealthCheck();
        }, 60000); // 60s
    }
    scheduleNextHealthCheck();
    
    var observer = new MutationObserver(function(mutations) {
        if (window.ns_observer_timeout) {
            clearTimeout(window.ns_observer_timeout);
        }
        window.ns_observer_timeout = setTimeout(function() {
            // Disconnect to avoid self-triggering during our own mutations
            observer.disconnect();
            
            try {
                initSubscriptionTab();
                updateBadgeState(); 
                
                // Trigger a health check if we just entered the inventory area and haven't checked recently
                var $invNav = $('#nav-inventory');
                var isCurrentlyInventory = $invNav.length > 0 && ($invNav.hasClass('nav-link-current') || $invNav.hasClass('active'));
                
                if (isCurrentlyInventory && !window.ns_was_inventory) {
                    checkSubscriptionHealth();
                }
                window.ns_was_inventory = isCurrentlyInventory;
            } finally {
                // Re-observe
                observer.observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ['class'] });
            }
        }, 300); // 300ms debounce for DOM noise
    });
    observer.observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ['class'] });

    // Also bind click on nav to be responsive
    $(document).on('click', '#nav-buttons li a', function() {
        setTimeout(updateBadgeState, 100); // Small delay for class update
    });

})();
