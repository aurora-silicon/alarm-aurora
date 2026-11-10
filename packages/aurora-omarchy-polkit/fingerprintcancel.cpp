#include <QDBusConnection>
#include <QDBusMessage>
#include <QQmlExtensionPlugin>
#include <QRegularExpression>
#include <qqml.h>

class FingerprintCancel : public QObject
{
  Q_OBJECT

public:
  using QObject::QObject;

  Q_INVOKABLE bool choosePassword(const QString &token) const
  {
    static const QRegularExpression validToken(QStringLiteral("\\A[0-9a-f]{32}\\z"));
    if (!validToken.match(token).hasMatch())
      return false;

    const auto signal = QDBusMessage::createSignal(
      QStringLiteral("/net/reactivated/Fprint/PasswordSwitch/") + token,
      QStringLiteral("net.reactivated.Fprint.PasswordSwitch"),
      QStringLiteral("UsePassword"));
    return QDBusConnection::systemBus().send(signal);
  }
};

class FingerprintCancelPlugin : public QQmlExtensionPlugin
{
  Q_OBJECT
  Q_PLUGIN_METADATA(IID QQmlExtensionInterface_iid)

public:
  void registerTypes(const char *uri) override
  {
    qmlRegisterType<FingerprintCancel>(uri, 1, 0, "FingerprintCancel");
  }
};

#include "fingerprintcancel.moc"
