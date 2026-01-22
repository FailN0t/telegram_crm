/**
 * Telegram CRM Widget для AmoCRM
 * Встраивает iframe с чатом Telegram в карточку контакта
 */

define(['jquery'], function($) {
    var CustomWidget = function() {
        var self = this;

        /**
         * Инициализация виджета
         */
        this.callbacks = {
            render: function() {
                console.log('Telegram CRM Widget initialized');
                return true;
            },

            init: function() {
                console.log('Widget init called');
                return true;
            },

            bind_actions: function() {
                console.log('Widget bind_actions called');
                return true;
            },

            settings: function() {
                console.log('Widget settings called');
                return true;
            },

            onSave: function() {
                console.log('Widget onSave called');
                return true;
            },

            destroy: function() {
                console.log('Widget destroy called');
            },

            contacts: {
                selected: function() {
                    console.log('Contact selected');
                },

                /**
                 * Отрисовка виджета в карточке контакта
                 */
                render: function() {
                    var $widget_area = $('#' + self.get_settings().widget_code + '_right_' + self.system().area);

                    if (!$widget_area.length) {
                        return false;
                    }

                    // Получить ID контакта
                    var contact_id = self.system().amocard_id;

                    if (!contact_id) {
                        console.error('Contact ID not found');
                        return false;
                    }

                    // URL iframe
                    var iframe_url = 'https://your-server.example.com/api/amocrm/widget/chat?contact_id=' + contact_id;

                    // Создать iframe
                    var $iframe = $('<iframe>', {
                        src: iframe_url,
                        style: 'width: 100%; height: 600px; border: none; border-radius: 8px;',
                        id: 'telegram_crm_widget_iframe'
                    });

                    // Заголовок виджета
                    var $header = $('<div>', {
                        style: 'padding: 10px 0; font-size: 16px; font-weight: bold; color: #333;',
                        text: '💬 Telegram'
                    });

                    // Контейнер виджета
                    var $container = $('<div>', {
                        style: 'padding: 15px; background: #f5f5f5; border-radius: 8px; margin-top: 10px;'
                    }).append($header).append($iframe);

                    // Добавить в карточку
                    $widget_area.html($container);

                    console.log('Telegram widget rendered for contact:', contact_id);

                    return true;
                }
            },

            leads: {
                selected: function() {
                    console.log('Lead selected');
                },

                /**
                 * Отрисовка виджета в карточке сделки
                 */
                render: function() {
                    // Аналогично контактам
                    var $widget_area = $('#' + self.get_settings().widget_code + '_right_' + self.system().area);

                    if (!$widget_area.length) {
                        return false;
                    }

                    var lead_id = self.system().amocard_id;

                    if (!lead_id) {
                        return false;
                    }

                    // Получить главный контакт сделки
                    var lead = self.crm_post(
                        'https://' + self.system().subdomain + '.amocrm.ru/api/v4/leads/' + lead_id,
                        {},
                        function(response) {
                            if (response && response._embedded && response._embedded.contacts && response._embedded.contacts.length > 0) {
                                var contact_id = response._embedded.contacts[0].id;
                                var iframe_url = 'https://your-server.example.com/api/amocrm/widget/chat?contact_id=' + contact_id;

                                var $iframe = $('<iframe>', {
                                    src: iframe_url,
                                    style: 'width: 100%; height: 600px; border: none; border-radius: 8px;',
                                    id: 'telegram_crm_widget_iframe'
                                });

                                var $header = $('<div>', {
                                    style: 'padding: 10px 0; font-size: 16px; font-weight: bold; color: #333;',
                                    text: '💬 Telegram'
                                });

                                var $container = $('<div>', {
                                    style: 'padding: 15px; background: #f5f5f5; border-radius: 8px; margin-top: 10px;'
                                }).append($header).append($iframe);

                                $widget_area.html($container);
                            }
                        },
                        'GET'
                    );

                    return true;
                }
            },

            companies: {
                selected: function() {
                    console.log('Company selected');
                },

                /**
                 * Отрисовка виджета в карточке компании
                 */
                render: function() {
                    // Аналогично контактам
                    return true;
                }
            }
        };

        return this;
    };

    return CustomWidget;
});
