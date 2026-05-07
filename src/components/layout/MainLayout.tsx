import type { ReactNode } from "react";
import { Topbar } from "./Topbar";

type MainLayoutProps = {
  children: ReactNode;
  breadcrumb?: string;
  userName?: string;
  hasUnreadNotifications?: boolean;
  onNotificationsClick?: () => void;
  onNavigate?: (href: string) => void;
  onUserAction?: (action: "profile" | "settings" | "theme" | "logout") => void;
  onCreateInvoice?: () => void;
  onCreateReservation?: () => void;
  onCreateCustomer?: () => void;
  searchResults?: {
    customers?: Array<{ id: string; name: string }>;
    properties?: Array<{ id: string; name: string }>;
    invoices?: Array<{ id: string; code: string }>;
  };
};

export function MainLayout({
  children,
  breadcrumb,
  userName,
  hasUnreadNotifications,
  onNotificationsClick,
  onNavigate,
  onUserAction,
  onCreateInvoice,
  onCreateReservation,
  onCreateCustomer,
  searchResults,
}: MainLayoutProps) {
  return (
    <div
      style={{
        minHeight: "100vh",
        background: "var(--bg)",
        color: "var(--text)",
      }}
    >
      <Topbar
        breadcrumb={breadcrumb}
        userName={userName}
        hasUnreadNotifications={hasUnreadNotifications}
        onNotificationsClick={onNotificationsClick}
        onNavigate={onNavigate}
        onUserAction={onUserAction}
        onCreateInvoice={onCreateInvoice}
        onCreateReservation={onCreateReservation}
        onCreateCustomer={onCreateCustomer}
        searchResults={searchResults}
      />
      <main style={{ padding: 16 }}>{children}</main>
    </div>
  );
}
