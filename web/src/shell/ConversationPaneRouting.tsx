import {
  forwardRef,
  useCallback,
  useMemo,
  useRef,
  type ReactNode,
  type MutableRefObject,
} from "react";
import type { NavigateOptions, To } from "react-router-dom";
import {
  RoutingProvider,
  useRouting,
  type OmnigentLinkProps,
  type RoutingApi,
} from "@/lib/routing";

/** Keep session navigation inside the selected pane, including menus and new-chat links. */
export function ConversationPaneRouting({
  onNavigate,
  children,
}: {
  onNavigate: (to: To, options?: NavigateOptions) => boolean;
  children: ReactNode;
}) {
  const base = useRouting();
  const latest = useRef(onNavigate);
  latest.current = onNavigate;
  const routing = useMemo(() => paneRouting(base, latest), [base]);
  return <RoutingProvider value={routing}>{children}</RoutingProvider>;
}

function paneRouting(
  base: RoutingApi,
  latest: MutableRefObject<(to: To, options?: NavigateOptions) => boolean>,
): RoutingApi {
  return {
    ...base,
    useNavigate: () => {
      const navigate = base.useNavigate();
      return useCallback(
        ((to: To | number, options?: NavigateOptions) => {
          if (typeof to === "number") return navigate(to);
          if (!latest.current(to, options)) return navigate(to, options);
        }) as ReturnType<RoutingApi["useNavigate"]>,
        [navigate],
      );
    },
    Link: forwardRef<HTMLAnchorElement, OmnigentLinkProps>(function PaneLink(props, ref) {
      const Link = base.Link;
      return (
        <Link
          {...props}
          ref={ref}
          onClick={(event) => {
            props.onClick?.(event);
            if (
              event.defaultPrevented ||
              event.button !== 0 ||
              event.ctrlKey ||
              event.metaKey ||
              event.shiftKey ||
              event.altKey ||
              (props.target && props.target !== "_self") ||
              props.download
            )
              return;
            if (latest.current(props.to, { replace: props.replace, state: props.state }))
              event.preventDefault();
          }}
        />
      );
    }),
  };
}
