#include <QCoreApplication>
#include <QDBusConnection>
#include <QDBusMessage>
#include <QQmlExtensionPlugin>
#include <QRegularExpression>
#include <qqml.h>

class FingerprintCancel : public QObject
{
  Q_OBJECT

public:
  explicit FingerprintCancel(QObject *parent = nullptr)
    : QObject(parent),
      m_name(QStringLiteral("net.reactivated.Fprint.PasswordSwitch.Agent.p") +
             QString::number(QCoreApplication::applicationPid())),
      m_registered(QDBusConnection::systemBus().registerService(m_name))
  {
  }

  ~FingerprintCancel() override
  {
    if (m_registered)
      QDBusConnection::systemBus().unregisterService(m_name);
  }

  Q_INVOKABLE bool choosePassword(const QString &token) const
  {
    static const QRegularExpression validToken(QStringLiteral("\\A[0-9a-f]{32}\\z"));
    if (!m_registered || !validToken.match(token).hasMatch())
      return false;

    const auto signal = QDBusMessage::createSignal(
      QStringLiteral("/net/reactivated/Fprint/PasswordSwitch/") + token,
      QStringLiteral("net.reactivated.Fprint.PasswordSwitch"),
      QStringLiteral("UsePassword"));
    return QDBusConnection::systemBus().send(signal);
  }
private:
  QString m_name;
  bool m_registered;
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
