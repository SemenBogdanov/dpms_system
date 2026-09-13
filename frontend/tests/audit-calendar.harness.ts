import React from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Routes, Route, Link } from 'react-router-dom'
import { installAuditCalendarNavigationGuard } from '../src/lib/auditCalendarNavigation'
import AuditCalendarPage from '../src/pages/AuditCalendarPage'
import { AuditCalendarAdminPanel } from '../src/components/audit-calendar/AuditCalendarAdminPanel'
import '../src/index.css'

installAuditCalendarNavigationGuard()
createRoot(document.getElementById('root')!).render(React.createElement(BrowserRouter, null,
  React.createElement(React.Fragment, null,
    React.createElement(Link, { to: '/other' }, 'Соседняя страница'),
    React.createElement(Routes, null,
      React.createElement(Route, { path: '/audit-calendar', element: React.createElement(AuditCalendarPage) }),
      React.createElement(Route, { path: '/calendar-admin', element: React.createElement(AuditCalendarAdminPanel) }),
      React.createElement(Route, { path: '/other', element: React.createElement(Link, { to: '/audit-calendar?from=2026-09-14&to=2026-09-20' }, 'Календарь') }),
    ),
  ),
))
